"""Worker: gera rascunhos de resposta para comentários novos (Instagram e Facebook).

Roda no mesmo loop do Worker de mensagens, com prioridade menor: só pega um
comentário quando a fila de mensagens do Direct está vazia. O rascunho NÃO é
publicado aqui: fica `pending` até alguém aprovar no painel.
"""

import structlog
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.agents.comments import generate_draft
from whatsapp_langchain.shared.comments import (
    FACEBOOK,
    claim_next_comment_for_draft,
    mark_draft_failed,
    save_draft,
    upsert_post,
)
from whatsapp_langchain.worker.facebook_client import FacebookPageClient
from whatsapp_langchain.worker.instagram_client import InstagramClient

logger = structlog.get_logger()


async def _post_caption(
    pool: AsyncConnectionPool,
    media_id: str,
    channel: str,
    instagram: InstagramClient,
    facebook: FacebookPageClient | None,
) -> str | None:
    """Busca a postagem na Graph API do canal e salva (best-effort).

    Sem a legenda o rascunho ainda sai (a IA só tem menos contexto), então
    qualquer falha aqui é registrada e ignorada.
    """
    try:
        if channel == FACEBOOK:
            if facebook is None:
                return None
            post = await facebook.get_post(media_id)
        else:
            post = await instagram.get_media(media_id)
    except Exception as exc:
        logger.warning(
            "comment_post_fetch_failed",
            media_id=media_id,
            channel=channel,
            error=str(exc),
        )
        return None
    if post.get("id"):
        await upsert_post(pool, post, channel=channel)
    return post.get("caption")


async def draft_next_comment(
    pool: AsyncConnectionPool,
    instagram: InstagramClient,
    *,
    facebook: FacebookPageClient | None = None,
    lease_seconds: int = 60,
) -> bool:
    """Gera o rascunho do próximo comentário `new`, se houver.

    Returns:
        True se um comentário foi processado (com sucesso ou falha).
    """
    comment = await claim_next_comment_for_draft(pool, lease_seconds)
    if comment is None:
        return False

    caption = comment.post_caption
    if not comment.post_synced:
        caption = (
            await _post_caption(
                pool, comment.media_id, comment.channel, instagram, facebook
            )
            or caption
        )

    try:
        draft = await generate_draft(
            comment_text=comment.text,
            from_username=comment.from_username,
            post_caption=caption,
            is_reply=comment.parent_id is not None,
            channel=comment.channel,
        )
    except Exception as exc:
        logger.error(
            "comment_draft_failed",
            comment_id=comment.comment_id,
            channel=comment.channel,
            attempts=comment.attempts,
            error=str(exc),
        )
        await mark_draft_failed(pool, comment.comment_id, str(exc), comment.attempts)
        return True

    await save_draft(
        pool,
        comment.comment_id,
        draft_public=draft.public,
        draft_private=draft.private,
        suggests_ignore=draft.ignore,
        reason=draft.reason,
    )
    logger.info(
        "comment_draft_saved",
        comment_id=comment.comment_id,
        media_id=comment.media_id,
        channel=comment.channel,
        suggests_ignore=draft.ignore,
        has_private=bool(draft.private),
    )
    return True
