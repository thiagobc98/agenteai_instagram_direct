"""Webhook do Instagram Direct — processamento assíncrono via fila.

Recebe eventos da Instagram Messaging API (Meta), valida a assinatura
X-Hub-Signature-256, extrai as mensagens (texto ou URL de mídia), aplica
rate limit e coloca na fila para processamento pelo Worker.

Fluxo: Meta -> POST /webhook/instagram?agent=... -> Fila -> Worker

O mesmo caminho atende os dois métodos que a Meta usa:
- GET: handshake de verificação ao cadastrar o webhook no painel do app.
- POST: entrega dos eventos, assinada com o App Secret.

Configure a URL de callback no painel da Meta como:
    https://seu-dominio/webhook/instagram?agent=secretaria

Uso (verificação):
    curl "http://localhost:8000/webhook/instagram?hub.mode=subscribe\
&hub.verify_token=SEU_TOKEN&hub.challenge=1234"
"""

import hmac
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from whatsapp_langchain.agents.loader import AgentNotFoundError, list_agents
from whatsapp_langchain.server.dependencies import (
    check_rate_limit,
    validate_instagram_signature,
)
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.instagram_payload import parse_instagram_messages
from whatsapp_langchain.shared.queue import enqueue_or_buffer

logger = structlog.get_logger()

router = APIRouter(tags=["webhook"])


@router.get("/webhook/instagram", response_class=PlainTextResponse)
async def verify_instagram_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> str:
    """Responde ao handshake de verificação da Meta.

    Args:
        hub_mode: Sempre "subscribe" no handshake.
        hub_verify_token: Token que a Meta devolve — deve bater com
            INSTAGRAM_VERIFY_TOKEN.
        hub_challenge: Valor a ser devolvido em texto puro.

    Returns:
        O `hub.challenge`, em texto puro.

    Raises:
        HTTPException 403: Se o token não confere ou o modo é inválido.
        HTTPException 500: Se INSTAGRAM_VERIFY_TOKEN não está configurado.
    """
    verify_token = settings.instagram_verify_token
    if verify_token is None or not verify_token.get_secret_value():
        logger.error("instagram_verify_token_not_configured")
        raise HTTPException(
            status_code=500, detail="Instagram verify token not configured"
        )

    if (
        hub_mode != "subscribe"
        or hub_challenge is None
        or not hmac.compare_digest(
            hub_verify_token or "", verify_token.get_secret_value()
        )
    ):
        logger.warning("instagram_verification_failed", mode=hub_mode)
        raise HTTPException(status_code=403, detail="Verification failed")

    logger.info("instagram_webhook_verified")
    return hub_challenge


@router.post("/webhook/instagram")
async def webhook_instagram(
    request: Request,
    agent: str = Query(
        description="ID do agente para processar a mensagem",
    ),
    _valid: None = Depends(validate_instagram_signature),
) -> dict:
    """Recebe webhook do Instagram e enfileira para processamento.

    O Worker consome a mensagem da fila, executa o agente, e envia a
    resposta via Instagram Messaging API. Eventos que não são mensagens
    recebidas (ecos das mensagens enviadas pela própria conta, confirmações
    de leitura, reações, mensagens apagadas) são silenciosamente ignorados.

    Um POST pode trazer várias mensagens; cada uma é enfileirada
    individualmente. Estouro de rate limit descarta só a mensagem afetada
    — devolver erro faria a Meta reenviar o lote inteiro (duplicando as
    mensagens já enfileiradas).

    Args:
        request: Request HTTP (body já validado pela assinatura).
        agent: ID do agente (query param).

    Returns:
        Confirmação de recebimento com a contagem de mensagens enfileiradas.
    """
    available_agents = list_agents()
    if agent not in available_agents:
        raise AgentNotFoundError(agent)

    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    messages = parse_instagram_messages(payload)
    if not messages:
        return {"ignored": True}

    pool = await get_pool()
    enqueued = 0

    for parsed in messages:
        if (
            settings.instagram_business_account_id
            and parsed.external_id == settings.instagram_business_account_id
        ):
            continue

        try:
            await check_rate_limit(parsed.external_id)
        except HTTPException as exc:
            if exc.status_code != 429:
                raise
            logger.warning(
                "webhook_instagram_rate_limited",
                external_id=parsed.external_id,
                message_id=parsed.message_id,
            )
            continue

        result = await enqueue_or_buffer(
            pool=pool,
            external_id=parsed.external_id,
            agent_id=agent,
            body=parsed.body,
            media_url=parsed.media_url,
            media_type=parsed.media_type,
            message_id=parsed.message_id,
            buffer_seconds=settings.message_buffer_seconds,
        )
        enqueued += 1

        logger.info(
            "webhook_instagram_received",
            external_id=parsed.external_id,
            agent_id=agent,
            message_id=result.message_id,
            buffered=result.is_buffered,
        )

    return {"received": True, "enqueued": enqueued}
