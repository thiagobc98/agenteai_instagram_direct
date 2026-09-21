"""Webhook do Evolution API — processamento assíncrono via fila.

Recebe eventos do Evolution API (self-hosted), valida o token secreto do
path, extrai a mensagem (texto ou mídia em base64), aplica rate limit, e
coloca na fila para processamento pelo Worker.

Fluxo: Evolution API (VPS) -> POST /webhook/evolution/{token} -> Fila -> Worker

O Evolution não assina os webhooks (sem equivalente ao X-Twilio-Signature),
por isso a validação é feita via token secreto no próprio path — configure
a URL no Evolution Manager como:
    https://seu-dominio/webhook/evolution/{EVOLUTION_WEBHOOK_TOKEN}?agent=...

Uso:
    curl -X POST ".../webhook/evolution/SEU_TOKEN?agent=secretaria" \
         -H "Content-Type: application/json" \
         -d '{"event":"messages.upsert","data":{...}}'
"""

import structlog
from fastapi import APIRouter, Body, Depends, Query

from whatsapp_langchain.agents.loader import AgentNotFoundError, list_agents
from whatsapp_langchain.server.dependencies import (
    check_rate_limit,
    validate_evolution_webhook_token,
)
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.evolution_payload import parse_evolution_message
from whatsapp_langchain.shared.queue import enqueue_or_buffer

logger = structlog.get_logger()

router = APIRouter(tags=["webhook"])


@router.post("/webhook/evolution/{token}")
async def webhook_evolution(
    token: str,
    agent: str = Query(
        description="ID do agente para processar a mensagem",
    ),
    payload: dict = Body(
        description="Payload de webhook do Evolution API (evento messages.upsert).",
    ),
    _valid: None = Depends(validate_evolution_webhook_token),
) -> dict:
    """Recebe webhook do Evolution API e enfileira para processamento.

    O Worker consome a mensagem da fila, executa o agente, e envia a
    resposta via Evolution API. Eventos que não são mensagens de texto/mídia
    recebidas (ex: confirmações de entrega, mensagens enviadas pelo próprio
    bot, mensagens de grupo) são silenciosamente ignorados.

    Args:
        token: Token secreto validado via dependency (path).
        agent: ID do agente (query param).
        payload: Corpo JSON do webhook.

    Returns:
        Confirmação de recebimento (ou de que o evento foi ignorado).
    """
    available_agents = list_agents()
    if agent not in available_agents:
        raise AgentNotFoundError(agent)

    parsed = parse_evolution_message(payload)
    if parsed is None:
        return {"ignored": True}

    if not parsed.phone_number:
        logger.warning("webhook_missing_sender", message_id=parsed.message_id)
        return {"ignored": True}

    await check_rate_limit(parsed.phone_number)

    pool = await get_pool()
    result = await enqueue_or_buffer(
        pool=pool,
        phone_number=parsed.phone_number,
        agent_id=agent,
        body=parsed.body,
        media_base64=parsed.media_base64,
        media_type=parsed.media_type,
        message_id=parsed.message_id,
        buffer_seconds=settings.message_buffer_seconds,
    )

    logger.info(
        "webhook_evolution_received",
        phone=parsed.phone_number,
        agent_id=agent,
        message_id=result.message_id,
        buffered=result.is_buffered,
    )

    return {"received": True}
