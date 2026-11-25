"""Envia ao atendente, pelo WhatsApp (Wuzapi), os avisos de mensagens do Direct.

Roda numa tarefa própria do Worker (`notification_loop`), separada do
atendimento: o aviso sai em segundos mesmo com a fila do Direct cheia, e uma
falha aqui nunca afeta a resposta à cliente.
"""

from __future__ import annotations

import asyncio

import structlog
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.shared import attendant_notify as store
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.wuzapi_client import (
    WuzapiClient,
    WuzapiError,
    build_wuzapi_client,
)

logger = structlog.get_logger()

POLL_SECONDS = 2.0
# JID de cada destinatário (com ou sem o 9), descoberto uma vez por processo
_jid_cache: dict[str, str] = {}


def panel_chat_url(external_id: str) -> str | None:
    """Link do painel, só se ele estiver num endereço público (https)."""
    origin = settings.frontend_origin.rstrip("/")
    if not origin.startswith("https://"):
        return None
    return f"{origin}/chats/{external_id}"


async def resolve_recipient(wuzapi: WuzapiClient, phone: str) -> str:
    """JID do número no WhatsApp; se a checagem falhar, usa o número como veio."""
    if phone in _jid_cache:
        return _jid_cache[phone]
    try:
        jid = await wuzapi.whatsapp_jid(phone)
    except WuzapiError as exc:
        logger.info("attendant_jid_check_failed", error=exc.detail)
        return phone
    if jid is None:
        raise WuzapiError(404, f"o número {phone} não tem WhatsApp")
    _jid_cache[phone] = jid
    return jid


async def _contact(
    pool: AsyncConnectionPool, external_id: str
) -> tuple[str | None, str | None]:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT username, name FROM contacts WHERE external_id = %s", (external_id,)
        )
        row = await cursor.fetchone()
    return (row[0], row[1]) if row else (None, None)


async def notify_next(pool: AsyncConnectionPool, wuzapi: WuzapiClient | None) -> bool:
    """Envia o próximo lote de avisos. True se havia algo para fazer."""
    items = await store.claim_batch(pool)
    if not items:
        return False
    ids = [i.id for i in items]

    config = await store.get_settings(pool)
    if not config.enabled:
        await store.mark_skipped(pool, ids, "avisos desligados no painel")
        return True
    if not config.recipients:
        await store.mark_skipped(pool, ids, "nenhum celular cadastrado")
        return True
    if wuzapi is None:
        await store.mark_skipped(pool, ids, "Wuzapi não configurado no .env")
        return True

    username, name = await _contact(pool, items[0].external_id)
    text = store.format_notification(
        items,
        username=username,
        name=name,
        panel_url=panel_chat_url(items[0].external_id),
    )

    errors: list[str] = []
    for phone in config.recipients:
        try:
            await wuzapi.send_text(await resolve_recipient(wuzapi, phone), text)
        except WuzapiError as exc:
            errors.append(f"{phone}: {exc.detail}")
        except Exception as exc:  # rede, timeout
            errors.append(f"{phone}: {type(exc).__name__}")

    if len(errors) < len(config.recipients):
        # Chegou para pelo menos um: não reenvia (repetiria para quem recebeu)
        await store.mark_sent(pool, ids, "; ".join(errors) or None)
        logger.info(
            "attendant_notified",
            external_id=items[0].external_id,
            messages=len(items),
            failed_recipients=len(errors),
        )
    else:
        gave_up = await store.mark_failed(pool, items, "; ".join(errors))
        logger.warning(
            "attendant_notify_failed",
            external_id=items[0].external_id,
            gave_up=gave_up,
            error=errors[0][:200],
        )
    return True


async def notification_loop(pool: AsyncConnectionPool) -> None:
    """Loop infinito do Worker. Nunca deixa uma exceção derrubar o processo."""
    wuzapi = build_wuzapi_client()
    logger.info("attendant_notifier_ready", wuzapi_configured=wuzapi is not None)
    while True:
        try:
            await store.skip_stale(pool)
            while await notify_next(pool, wuzapi):
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("attendant_notifier_error", error=str(exc))
        await asyncio.sleep(POLL_SECONDS)
