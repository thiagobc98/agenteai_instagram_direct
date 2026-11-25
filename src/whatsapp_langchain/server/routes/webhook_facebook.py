"""Webhook da Página do Facebook: comentários nos posts (campo `feed`).

Fluxo: Meta -> POST /webhook/facebook -> ig_comments (channel=facebook)
-> Worker escreve o rascunho -> equipe aprova na tela "Facebook" do painel.

Cadastro no painel da Meta (produto Webhooks, objeto "Page"):
    URL de retorno: https://SEU-DOMINIO/webhook/facebook
    Verificar token: FACEBOOK_VERIFY_TOKEN (ou INSTAGRAM_VERIFY_TOKEN)
    Campo assinado: feed

Segurança:
- POST só é aceito com assinatura HMAC-SHA256 válida (FACEBOOK_APP_SECRET),
  comparada em tempo constante; sem segredo configurado, nada entra.
- Eventos de outras Páginas são descartados (o app pode servir várias).
- O corpo nunca é registrado em log (tem nome e texto de terceiros).
- Sempre 200 para eventos válidos que não interessam: um erro faria a Meta
  reenviar o lote e, depois de muitas falhas, desativar o webhook.
"""

from __future__ import annotations

import hmac
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from whatsapp_langchain.server.dependencies import validate_facebook_signature
from whatsapp_langchain.shared import comments as store
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.facebook_comments_payload import (
    VERB_ADD,
    VERB_REMOVE,
    parse_facebook_comments,
)

logger = structlog.get_logger()

router = APIRouter(tags=["webhook"])


def _verify_token() -> str:
    for token in (settings.facebook_verify_token, settings.instagram_verify_token):
        if token is not None and token.get_secret_value():
            return token.get_secret_value()
    return ""


@router.get("/webhook/facebook", response_class=PlainTextResponse)
async def verify_facebook_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> str:
    """Handshake de verificação da Meta: devolve o `hub.challenge`."""
    expected = _verify_token()
    if not expected:
        logger.error("facebook_verify_token_not_configured")
        raise HTTPException(status_code=503, detail="Verify token not configured")
    if (
        hub_mode != "subscribe"
        or hub_challenge is None
        or not hmac.compare_digest(hub_verify_token or "", expected)
    ):
        logger.warning("facebook_verification_failed", mode=hub_mode)
        raise HTTPException(status_code=403, detail="Verification failed")
    logger.info("facebook_webhook_verified")
    return hub_challenge


@router.post("/webhook/facebook")
async def webhook_facebook(
    request: Request,
    _valid: None = Depends(validate_facebook_signature),
) -> dict:
    """Grava os comentários novos da Página para a IA rascunhar a resposta."""
    if not settings.facebook_page_id:
        # Assinatura válida, mas sem Página configurada não há o que fazer
        return {"ignored": True}
    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    events = parse_facebook_comments(payload, page_id=settings.facebook_page_id)
    if not events:
        return {"ignored": True}

    pool = await get_pool()
    saved = removed = 0
    for event in events:
        if event.verb == VERB_REMOVE:
            # Apagado pela pessoa (ou ocultado): não há mais o que responder.
            # set_status não mexe em comentário já respondido.
            removed += int(await store.set_status(pool, event.comment_id, "ignored"))
            continue
        if event.verb != VERB_ADD:
            # Edição: o rascunho foi feito sobre o texto original; a equipe vê
            # o comentário atualizado ao abrir o post no Facebook
            continue

        created = await store.insert_comment(
            pool,
            comment_id=event.comment_id,
            media_id=event.post_id,
            text=event.text,
            from_id=event.from_id,
            from_username=event.from_name,
            parent_id=event.parent_id,
            commented_at=event.commented_at,
            status="ignored" if event.is_own else "new",
            channel=store.FACEBOOK,
        )
        saved += int(created)
        logger.info(
            "webhook_facebook_comment_received",
            comment_id=event.comment_id,
            post_id=event.post_id,
            is_own=event.is_own,
            duplicate=not created,
        )

    return {"received": True, "comments": saved, "removed": removed}
