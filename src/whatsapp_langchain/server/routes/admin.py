"""Rotas administrativas para o painel de controle.

Endpoints para visualizar conversas, métricas e agentes disponíveis.
Usado pelo frontend (Next.js Admin Panel).

Uso:
    curl http://localhost:8000/api/agents
    curl http://localhost:8000/api/chats?limit=20
    curl http://localhost:8000/api/chats/17841400000000000
    curl http://localhost:8000/api/metrics
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Query

from whatsapp_langchain.agents.loader import list_agents
from whatsapp_langchain.shared.analytics import build_dashboard
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.google_calendar import (
    GoogleCalendarNotConfiguredError,
    list_events,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/agents")
async def get_agents() -> dict[str, list[str]]:
    """Lista agentes disponíveis no catálogo.

    Returns:
        Lista de agent_ids registrados.
    """
    return {"agents": list_agents()}


@router.get("/chats")
async def get_chats(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Lista conversas ativas, ordenadas por última mensagem.

    Args:
        limit: Máximo de resultados (1-100). Default: 20.
        offset: Offset para paginação. Default: 0.

    Returns:
        Lista de conversas com paginação.
    """
    pool = await get_pool()

    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT v.external_id, v.agent_id, v.thread_id, v.last_message,
                   v.last_message_at, v.message_count, v.created_at,
                   c.username, c.name, c.profile_pic_url, c.whatsapp
            FROM conversations v
            LEFT JOIN contacts c ON c.external_id = v.external_id
            ORDER BY v.last_message_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()

        # Total para paginação
        count_cursor = await conn.execute("SELECT COUNT(*) FROM conversations")
        count_row = await count_cursor.fetchone()
        total = count_row[0] if count_row else 0

    chats = [
        {
            "external_id": row[0],
            "agent_id": row[1],
            "thread_id": row[2],
            "last_message": row[3],
            "last_message_at": row[4].isoformat() if row[4] else None,
            "message_count": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "username": row[7],
            "name": row[8],
            "profile_pic_url": row[9],
            "whatsapp": row[10],
        }
        for row in rows
    ]

    return {"chats": chats, "total": total, "limit": limit, "offset": offset}


@router.get("/chats/{external_id:path}")
async def get_chat_messages(
    external_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Lista mensagens de uma conversa específica.

    Args:
        external_id: ID do contato no Instagram (IGSID).
        limit: Máximo de resultados (1-200). Default: 50.
        offset: Offset para paginação. Default: 0.

    Returns:
        Lista de mensagens da conversa.
    """
    pool = await get_pool()

    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, agent_id, incoming_message, media_type,
                   normalized_input, media_processing_status,
                   response, status, created_at, processed_at,
                   media_processing_error, error
            FROM message_queue
            WHERE external_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (external_id, limit, offset),
        )
        rows = await cursor.fetchall()

        cursor = await conn.execute(
            """
            SELECT username, name, profile_pic_url, whatsapp
            FROM contacts WHERE external_id = %s
            """,
            (external_id,),
        )
        contact = await cursor.fetchone()

    messages = [
        {
            "id": row[0],
            "agent_id": row[1],
            "incoming_message": row[2],
            "media_type": row[3],
            "normalized_input": row[4],
            "media_processing_status": row[5],
            "response": row[6],
            "status": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "processed_at": row[9].isoformat() if row[9] else None,
            "media_processing_error": row[10],
            "error": row[11],
        }
        for row in rows
    ]

    return {
        "external_id": external_id,
        "username": contact[0] if contact else None,
        "name": contact[1] if contact else None,
        "profile_pic_url": contact[2] if contact else None,
        "whatsapp": contact[3] if contact else None,
        "messages": messages,
    }


@router.get("/dashboard")
async def get_dashboard(
    days: int = Query(default=14, ge=7, le=90),
) -> dict:
    """Indicadores de negócio da loja para o dashboard.

    Leads novos, clientes encaminhados à Patrícia, séries por dia, horários de
    pico, assuntos mais perguntados e mix de mensagens (ver
    `shared/analytics.py` para as definições).

    Args:
        days: Janela do período em dias (7-90). Default: 14.
    """
    pool = await get_pool()
    return await build_dashboard(
        pool,
        days=days,
        timezone=settings.business_timezone,
        handoff_phone=settings.handoff_phone,
    )


@router.get("/metrics")
async def get_metrics() -> dict:
    """Métricas operacionais da fila de mensagens.

    Returns:
        Métricas: total hoje, falhas, tempo médio de processamento, fila atual.
    """
    pool = await get_pool()

    async with pool.connection() as conn:
        # Total de mensagens hoje
        cursor = await conn.execute(
            """
            SELECT COUNT(*) FROM message_queue
            WHERE created_at >= CURRENT_DATE
            """
        )
        row = await cursor.fetchone()
        total_today = row[0] if row else 0

        # Falhas hoje
        cursor = await conn.execute(
            """
            SELECT COUNT(*) FROM message_queue
            WHERE status = 'failed' AND created_at >= CURRENT_DATE
            """
        )
        row = await cursor.fetchone()
        failures_today = row[0] if row else 0

        # Tempo médio de processamento (em segundos)
        cursor = await conn.execute(
            """
            SELECT AVG(EXTRACT(EPOCH FROM (processed_at - created_at)))
            FROM message_queue
            WHERE status = 'done' AND processed_at IS NOT NULL
              AND created_at >= CURRENT_DATE
            """
        )
        row = await cursor.fetchone()
        avg_processing_time = round(row[0], 2) if row and row[0] else None

        # Mensagens na fila agora
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM message_queue WHERE status = 'queued'"
        )
        row = await cursor.fetchone()
        queue_size = row[0] if row else 0

    return {
        "total_today": total_today,
        "failures_today": failures_today,
        "avg_processing_time_seconds": avg_processing_time,
        "queue_size": queue_size,
    }


@router.get("/calendar/events")
async def get_calendar_events(
    start: datetime = Query(description="Início do período (ISO 8601)"),
    end: datetime = Query(description="Fim do período (ISO 8601)"),
) -> dict:
    """Lista os eventos do Google Calendar em um período, para a Agenda do painel.

    Args:
        start: Início do período (ISO 8601).
        end: Fim do período (ISO 8601).

    Returns:
        `enabled=False` quando a integração não está configurada
        (GOOGLE_CALENDAR_ENABLED ou credenciais ausentes), sem erro —
        o painel mostra um estado vazio nesse caso.
    """
    if not settings.google_calendar_enabled:
        return {"enabled": False, "events": []}

    try:
        raw_events = await list_events(start, end)
    except GoogleCalendarNotConfiguredError:
        return {"enabled": False, "events": []}

    events = []
    for event in raw_events:
        start_info = event.get("start", {})
        end_info = event.get("end", {})
        private = event.get("extendedProperties", {}).get("private", {})
        events.append(
            {
                "id": event.get("id"),
                "summary": event.get("summary") or "(Sem título)",
                "start": start_info.get("dateTime") or start_info.get("date"),
                "end": end_info.get("dateTime") or end_info.get("date"),
                "all_day": "date" in start_info,
                # Eventos antigos (WhatsApp) guardavam o telefone em "phone".
                "external_id": private.get("external_id") or private.get("phone"),
                "patient_name": private.get("patient_name"),
            }
        )

    return {
        "enabled": True,
        "calendar_id": settings.google_calendar_id,
        "business_hour_start": settings.business_hour_start,
        "business_hour_end": settings.business_hour_end,
        "events": events,
    }
