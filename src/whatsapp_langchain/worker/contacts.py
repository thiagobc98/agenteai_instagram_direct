"""Mantém o perfil (@username, nome, foto) dos contatos em dia.

Tudo aqui é best-effort: falha ao buscar o perfil nunca pode atrasar nem
derrubar o atendimento — o painel apenas mostra o ID numérico.
"""

import structlog
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.shared.contacts import (
    list_contacts_without_profile,
    needs_profile_refresh,
    upsert_contact,
)
from whatsapp_langchain.worker.instagram_client import InstagramClient

logger = structlog.get_logger()


async def ensure_contact_profile(
    pool: AsyncConnectionPool, instagram: InstagramClient, external_id: str
) -> bool:
    """Busca e salva o perfil do contato se ainda não existe ou está velho.

    Returns:
        True se o perfil foi (re)buscado e salvo.
    """
    try:
        if not await needs_profile_refresh(pool, external_id):
            return False

        profile = await instagram.get_user_profile(external_id)
        if profile is None:
            return False

        await upsert_contact(
            pool,
            external_id,
            username=profile["username"],
            name=profile["name"],
            profile_pic_url=profile["profile_pic_url"],
        )
        logger.info(
            "contact_profile_saved",
            external_id=external_id,
            username=profile["username"],
        )
        return True
    except Exception as exc:
        logger.warning("contact_profile_error", external_id=external_id, error=str(exc))
        return False


async def backfill_contact_profiles(
    pool: AsyncConnectionPool, instagram: InstagramClient
) -> int:
    """Preenche o perfil dos contatos que conversaram antes desta funcionalidade."""
    try:
        pending = await list_contacts_without_profile(pool)
    except Exception as exc:
        logger.warning("contact_backfill_error", error=str(exc))
        return 0

    saved = 0
    for external_id in pending:
        if await ensure_contact_profile(pool, instagram, external_id):
            saved += 1
    logger.info("contact_backfill_done", pending=len(pending), saved=saved)
    return saved
