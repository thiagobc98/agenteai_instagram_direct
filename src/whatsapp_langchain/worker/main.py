"""Entry point do Worker — loop de processamento de mensagens.

Inicia o Worker que consome mensagens da fila PostgreSQL em loop.
Cada mensagem é processada pelo agente configurado.

Uso:
    python -m whatsapp_langchain.worker.main
"""

import asyncio

import structlog

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import (
    close_pool,
    get_pool,
    open_checkpointer,
    open_store,
    run_migrations,
)
from whatsapp_langchain.shared.observability import setup_logging
from whatsapp_langchain.worker.consumer import claim_next_message
from whatsapp_langchain.worker.contacts import (
    backfill_contact_profiles,
    ensure_contact_profile,
)
from whatsapp_langchain.worker.instagram_client import InstagramClient
from whatsapp_langchain.worker.processor import process_message

logger = structlog.get_logger()


async def main() -> None:
    """Loop principal do Worker.

    1. Configura logging e banco de dados
    2. Aplica migrações pendentes
    3. Entra em loop infinito buscando mensagens na fila
    4. Processa cada mensagem com o agente apropriado
    """
    setup_logging(log_level=settings.log_level, json_output=settings.log_json)
    logger.info("worker_starting")

    pool = await get_pool()
    await run_migrations(pool)
    checkpointer_stack, checkpointer = await open_checkpointer()
    await checkpointer.setup()

    store_stack, store = await open_store()
    if store:
        await store.setup()

    # Instagram Messaging API outbound: obrigatório — fail-fast se o token
    # de acesso está ausente.
    access_token = settings.instagram_access_token
    if access_token is None or not access_token.get_secret_value():
        logger.error(
            "instagram_credentials_missing", missing=["INSTAGRAM_ACCESS_TOKEN"]
        )
        msg = "Instagram obrigatório. Variáveis ausentes: INSTAGRAM_ACCESS_TOKEN"
        raise SystemExit(msg)

    instagram = InstagramClient(
        access_token=access_token.get_secret_value(),
        api_version=settings.instagram_graph_api_version,
        base_url=settings.instagram_graph_base_url,
    )
    logger.info(
        "instagram_client_ready",
        api_version=settings.instagram_graph_api_version,
        base_url=settings.instagram_graph_base_url,
    )

    logger.info(
        "worker_ready",
        poll_interval=settings.poll_interval_seconds,
        memory_enabled=store is not None,
    )

    # Contatos que conversaram antes do painel mostrar o @username
    await backfill_contact_profiles(pool, instagram)

    try:
        while True:
            message = await claim_next_message(pool, settings.lease_seconds)

            if message is None:
                await asyncio.sleep(settings.poll_interval_seconds)
                continue

            # Perfil (@username) do cliente para o painel — best-effort
            await ensure_contact_profile(pool, instagram, message.external_id)

            await process_message(
                message,
                pool,
                checkpointer=checkpointer,
                store=store,
                instagram=instagram,
            )

    except KeyboardInterrupt:
        logger.info("worker_interrupted")
    finally:
        if store_stack is not None:
            await store_stack.aclose()
        await checkpointer_stack.aclose()
        await close_pool()
        logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
