"""Rotas do painel para postagens e comentários (Instagram e Facebook).

Os dois canais usam as mesmas rotas, com `?channel=instagram|facebook`
(padrão: instagram, o comportamento de antes). Cada comentário guarda o seu
canal; aprovar responde pela rede de onde ele veio. A sincronização dos posts
do Facebook fica em `routes/facebook.py`.

A IA (Worker) deixa um rascunho de resposta pública + privada em cada
comentário novo; aqui o painel lista, edita, aprova (publica), ignora ou
pede um rascunho novo.

Uso:
    curl http://localhost:8000/api/posts
    curl -X POST http://localhost:8000/api/posts/sync
    curl http://localhost:8000/api/posts/<media_id>
    curl "http://localhost:8000/api/comments?status=pending"
    curl -X POST http://localhost:8000/api/comments/<id>/approve \
         -d '{"public_text": "...", "private_text": "..."}'
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from whatsapp_langchain.server.dependencies import require_admin_session
from whatsapp_langchain.shared import comments as store
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.worker.facebook_client import (
    FacebookGraphError,
    FacebookPageClient,
    build_facebook_client,
)
from whatsapp_langchain.worker.instagram_client import (
    MAX_COMMENT_CHARS,
    InstagramClient,
    InstagramSendError,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["comments"])

# A Meta só aceita resposta privada em até 7 dias depois do comentário.
# Na sincronização, comentários mais antigos entram como `archived` (sem
# rascunho da IA).
PRIVATE_REPLY_WINDOW = timedelta(days=7)

PENDING_STATUSES = ("new", "drafting", "pending", "failed")

# Agente do Direct (o mesmo do `?agent=` do webhook): a mensagem privada de um
# comentário entra na conversa do Direct desse agente no painel.
DIRECT_AGENT_ID = "secretaria"

Channel = Literal["instagram", "facebook"]
CHANNEL_QUERY = Query(default="instagram", description="instagram | facebook")


def _instagram() -> InstagramClient:
    token = settings.instagram_access_token
    if token is None or not token.get_secret_value():
        raise HTTPException(
            status_code=503, detail="INSTAGRAM_ACCESS_TOKEN não configurado"
        )
    return InstagramClient(
        access_token=token.get_secret_value(),
        api_version=settings.instagram_graph_api_version,
        base_url=settings.instagram_graph_base_url,
    )


def _graph_error(exc: InstagramSendError) -> HTTPException:
    if exc.is_token_invalid:
        detail = "Token do Instagram inválido ou expirado."
    elif exc.code == 10 or exc.code == 200:
        detail = (
            "O token não tem permissão para comentários "
            "(instagram_business_manage_comments)."
        )
    else:
        detail = f"Instagram recusou: {exc.detail}"
    return HTTPException(status_code=502, detail=detail)


def facebook_client_or_503() -> FacebookPageClient:
    facebook = build_facebook_client()
    if facebook is None:
        raise HTTPException(
            status_code=503,
            detail="Página do Facebook não configurada "
            "(FACEBOOK_PAGE_ID e FACEBOOK_PAGE_ACCESS_TOKEN no .env)",
        )
    return facebook


def facebook_error(exc: FacebookGraphError) -> HTTPException:
    """Erro da Graph API do Facebook em mensagem clara para o painel."""
    if exc.is_token_invalid:
        detail = "Token da Página do Facebook inválido ou expirado."
    elif exc.is_permission_error:
        detail = (
            "O token da Página não tem permissão para isso (confira "
            "pages_read_engagement, pages_manage_engagement e pages_messaging)."
        )
    else:
        detail = f"Facebook recusou: {exc.detail}"
    return HTTPException(status_code=502, detail=detail)


def _send_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FacebookGraphError):
        return facebook_error(exc)
    if isinstance(exc, InstagramSendError):
        return _graph_error(exc)
    return HTTPException(status_code=422, detail=str(exc))


def _parse_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("+0000", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Postagens
# ---------------------------------------------------------------------------


@router.get("/posts")
async def get_posts(
    limit: int = Query(default=60, ge=1, le=200),
    channel: Channel = CHANNEL_QUERY,
) -> dict:
    """Postagens conhecidas do canal, com contagem de comentários pendentes."""
    pool = await get_pool()
    posts = await store.list_posts(pool, limit=limit, channel=channel)
    counts = await store.comment_counts(pool, channel=channel)
    pending = sum(counts.get(s, 0) for s in PENDING_STATUSES)
    return {"posts": posts, "counts": counts, "pending_total": pending}


@router.post("/posts/sync")
async def sync_posts(limit: int = Query(default=25, ge=1, le=100)) -> dict:
    """Busca as postagens recentes e seus comentários na Graph API.

    Comentários novos dos últimos 7 dias, sem resposta da conta, entram como
    `new` (a IA rascunha). Os demais entram como `archived`, só para consulta.
    Comentários já conhecidos não são alterados.
    """
    instagram = _instagram()
    pool = await get_pool()

    try:
        account = await instagram.get_account()
        media = await instagram.list_media(limit=limit)
    except InstagramSendError as exc:
        raise _graph_error(exc) from exc

    own_ids = {str(account.get("user_id") or ""), str(account.get("id") or "")} - {""}
    own_username = (account.get("username") or "").lower()
    now = datetime.now(UTC)
    new_comments = 0
    failed_posts = 0

    for post in media:
        if not post.get("id"):
            continue
        await store.upsert_post(pool, post)
        if not post.get("comments_count"):
            continue

        try:
            items = await instagram.list_comments(post["id"])
        except InstagramSendError as exc:
            failed_posts += 1
            logger.warning(
                "comments_sync_post_failed", media_id=post["id"], error=str(exc)
            )
            continue

        def is_own(item: dict) -> bool:
            sender = item.get("from") if isinstance(item.get("from"), dict) else {}
            username = (item.get("username") or sender.get("username") or "").lower()
            return str(sender.get("id") or "") in own_ids or (
                bool(own_username) and username == own_username
            )

        answered = {item.get("parent_id") for item in items if is_own(item)}

        for item in items:
            sender = item.get("from") if isinstance(item.get("from"), dict) else {}
            commented_at = _parse_time(item.get("timestamp"))
            if is_own(item):
                status = "ignored"
            elif item["id"] in answered or now - commented_at > PRIVATE_REPLY_WINDOW:
                status = "archived"
            else:
                status = "new"

            created = await store.insert_comment(
                pool,
                comment_id=str(item["id"]),
                media_id=str(post["id"]),
                text=item.get("text") or "",
                from_id=str(sender["id"]) if sender.get("id") else None,
                from_username=item.get("username") or sender.get("username"),
                parent_id=str(item["parent_id"]) if item.get("parent_id") else None,
                commented_at=commented_at,
                status=status,
            )
            new_comments += int(created and status == "new")

    logger.info(
        "comments_sync_done",
        posts=len(media),
        new_comments=new_comments,
        failed_posts=failed_posts,
    )
    return {
        "posts": len(media),
        "new_comments": new_comments,
        "failed_posts": failed_posts,
    }


@router.get("/posts/{media_id}")
async def get_post(media_id: str) -> dict:
    """Uma postagem e todos os comentários registrados dela."""
    pool = await get_pool()
    post = await store.get_post(pool, media_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Postagem não encontrada")
    comments = await store.list_comments(
        pool, media_id=media_id, limit=500, channel=post["channel"]
    )
    return {"post": post, "comments": comments}


# ---------------------------------------------------------------------------
# Comentários
# ---------------------------------------------------------------------------


@router.get("/comments")
async def get_comments(
    status: str = Query(default="pending", description="pending | all | <status>"),
    limit: int = Query(default=100, ge=1, le=500),
    order: Literal["newest", "oldest"] = Query(default="oldest"),
    channel: Channel = CHANNEL_QUERY,
) -> dict:
    """Fila de aprovação (padrão) ou comentários de um status específico."""
    pool = await get_pool()
    if status == "pending":
        statuses: tuple[str, ...] | None = PENDING_STATUSES
    elif status == "all":
        statuses = None
    else:
        statuses = (status,)
    comments = await store.list_comments(
        pool,
        statuses=statuses,
        limit=limit,
        newest_first=order == "newest",
        channel=channel,
    )

    posts = {}
    for media_id in {c["media_id"] for c in comments}:
        post = await store.get_post(pool, media_id)
        if post:
            posts[media_id] = post
    return {"comments": comments, "posts": posts}


class ApproveRequest(BaseModel):
    public_text: str = Field(min_length=1, max_length=MAX_COMMENT_CHARS)
    # Vazio: não manda nada no Direct.
    private_text: str = Field(default="", max_length=1000)


@router.post("/comments/{comment_id}/approve")
async def approve_comment(
    comment_id: str,
    body: ApproveRequest,
    admin: str = Depends(require_admin_session),
) -> dict:
    """Publica a resposta pública e, se houver texto, a privada no Direct.

    Se a pública falhar, nada é enviado e o comentário fica `failed` (dá para
    tentar de novo). Se só a privada falhar, a pública continua publicada e o
    erro fica em `private_error`.
    """
    public_text = body.public_text.strip()
    private_text = body.private_text.strip()
    if not public_text:
        raise HTTPException(status_code=422, detail="Resposta pública vazia")
    if len(private_text.encode("utf-8")) > 1000:
        raise HTTPException(
            status_code=422, detail="Resposta privada passa de 1000 bytes"
        )

    pool = await get_pool()
    existing = await store.get_comment(pool, comment_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")
    # Cliente da rede do comentário. Falta de configuração vira 503 ANTES de
    # reservar o comentário (senão ele ficaria preso em `sending`).
    sender: InstagramClient | FacebookPageClient = (
        facebook_client_or_503()
        if existing["channel"] == store.FACEBOOK
        else _instagram()
    )

    comment = await store.claim_for_sending(pool, comment_id, approved_by=admin)
    if comment is None:
        existing = await store.get_comment(pool, comment_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Comentário não encontrado")
        raise HTTPException(
            status_code=409,
            detail=f"Comentário não pode ser respondido (status: {existing['status']})",
        )

    if not comment["reply_public_id"]:
        try:
            reply_id = await sender.reply_to_comment(comment_id, public_text)
        except (InstagramSendError, FacebookGraphError, ValueError) as exc:
            await store.mark_reply_failed(pool, comment_id, str(exc))
            raise _send_error(exc) from exc
        except Exception as exc:
            await store.mark_reply_failed(pool, comment_id, str(exc))
            raise
        await store.record_public_reply(pool, comment_id, reply_id, public_text)

    private_id = private_error = None
    if private_text and not comment["reply_private_id"]:
        try:
            private_id = await sender.send_private_reply(comment_id, private_text)
        except Exception as exc:
            private_error = (
                _send_error(exc).detail
                if isinstance(exc, InstagramSendError | FacebookGraphError)
                else str(exc)
            )
            logger.warning(
                "comment_private_reply_failed", comment_id=comment_id, error=str(exc)
            )

    await store.finish_reply(
        pool,
        comment_id,
        private_id=private_id,
        private_text=private_text if private_id else None,
        private_error=private_error,
    )
    # Só o Instagram tem a tela de conversas do Direct; no Facebook a
    # mensagem fica no Messenger da Página
    if private_id and comment.get("from_id") and comment["channel"] != store.FACEBOOK:
        # Best-effort: a resposta já saiu; falhar aqui só tira a conversa da
        # lista do painel, então não pode virar erro para quem aprovou
        try:
            await store.register_dm_from_comment(
                pool,
                from_id=comment["from_id"],
                username=comment.get("from_username"),
                agent_id=DIRECT_AGENT_ID,
                private_text=private_text,
            )
        except Exception as exc:
            logger.warning(
                "comment_dm_register_failed", comment_id=comment_id, error=str(exc)
            )
    return {"comment": await store.get_comment(pool, comment_id)}


@router.post("/comments/{comment_id}/ignore")
async def ignore_comment(comment_id: str) -> dict:
    pool = await get_pool()
    if not await store.set_status(pool, comment_id, "ignored"):
        raise HTTPException(status_code=409, detail="Comentário já respondido")
    return {"comment": await store.get_comment(pool, comment_id)}


@router.post("/comments/{comment_id}/reopen")
async def reopen_comment(comment_id: str) -> dict:
    """Volta um comentário ignorado/arquivado para a fila (pede rascunho novo)."""
    pool = await get_pool()
    if not await store.set_status(pool, comment_id, "new"):
        raise HTTPException(status_code=409, detail="Comentário já respondido")
    return {"comment": await store.get_comment(pool, comment_id)}


@router.post("/comments/{comment_id}/redraft")
async def redraft_comment(comment_id: str) -> dict:
    """Pede à IA um rascunho novo."""
    pool = await get_pool()
    if not await store.request_redraft(pool, comment_id):
        raise HTTPException(
            status_code=409, detail="Não dá para refazer o rascunho agora"
        )
    return {"comment": await store.get_comment(pool, comment_id)}
