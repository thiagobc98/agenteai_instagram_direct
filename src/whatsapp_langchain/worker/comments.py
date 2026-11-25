"""Worker: gera rascunhos de resposta para comentários novos.

Roda no mesmo loop do Worker de mensagens, com prioridade menor: só pega um
comentário quando a fila de mensagens do Direct está vazia. O rascunho NÃO é
publicado aqui: fica `pending` até alguém aprovar no painel.
"""

import structlog
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.agents.comments import generate_draft
from whatsapp_langchain.shared.comments import (
    claim_next_comment_for_draft,
    mark_draft_failed,
    save_draft,
    upsert_post,
)
from whatsapp_langchain.worker.instagram_client import InstagramClient

logger = structlog.get_logger()


async def _post_caption(
    pool: AsyncConnectionPool, instagram: InstagramClient, media_id: str
) -> str | None:
    """Busca a postagem na Graph API e salva (best-effort)."""
    try:
        post = await instagram.get_media(media_id)
    except Exception as exc:
        logger.warning("comment_post_fetch_failed", media_id=media_id, error=str(exc))
        return None
    if post.get("id"):
        await upsert_post(pool, post)
    return post.get("caption")


async def draft_next_comment(
    pool: AsyncConnectionPool,
    instagram: InstagramClient,
    *,
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
        caption = await _post_caption(pool, instagram, comment.media_id) or caption

    try:
        draft = await generate_draft(
            comment_text=comment.text,
            from_username=comment.from_username,
            post_caption=caption,
            is_reply=comment.parent_id is not None,
        )
    except Exception as exc:
        logger.error(
            "comment_draft_failed",
            comment_id=comment.comment_id,
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
        suggests_ignore=draft.ignore,
        has_private=bool(draft.private),
    )
    return True
