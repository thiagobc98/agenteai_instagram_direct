"""Notificações proativas via WhatsApp — fora do ciclo normal de webhook.

Diferente do fluxo padrão (responder a uma mensagem recebida), estas
funções enviam mensagens por iniciativa do sistema. Ambas são disparadas
uma vez por dia, em horário fixo, pelo loop do Worker (ver worker/main.py):

- `notify_doctor_tomorrow_schedule`: resumo para a médica com a agenda do
  dia seguinte, no horário configurado em `DOCTOR_SUMMARY_HOUR`.
- `send_patient_reminders`: lembrete de consulta para cada paciente com
  consulta amanhã, no horário configurado em `PATIENT_REMINDER_HOUR`.

Ambas usam `EvolutionClient.send_message` diretamente — sem passar pela
fila `message_queue` — e nunca propagam exceção: falha ao notificar não
deve interromper o loop do Worker.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from googleapiclient.errors import HttpError
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.google_calendar import (
    GoogleCalendarNotConfiguredError,
    list_events,
)
from whatsapp_langchain.worker.evolution_client import (
    EvolutionClient,
    EvolutionSendError,
)

logger = structlog.get_logger()


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.business_timezone)


def _tomorrow_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Retorna (início, fim) do dia seguinte a `now`, no fuso do negócio."""
    now = now or datetime.now(_tz())
    tomorrow_start = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return tomorrow_start, tomorrow_start + timedelta(days=1)


def _event_private(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("extendedProperties", {}).get("private", {})


async def notify_doctor_tomorrow_schedule(evolution: EvolutionClient) -> None:
    """Envia para o WhatsApp da médica a agenda completa do dia seguinte.

    Best-effort: nunca levanta exceção — chamada logo após um agendamento,
    remarcação ou cancelamento ter sucesso, não deve derrubar essa resposta
    ao paciente se a notificação falhar.
    """
    if not settings.doctor_whatsapp_number:
        return

    start, end = _tomorrow_range()

    try:
        events = await list_events(start, end)
    except GoogleCalendarNotConfiguredError:
        return
    except HttpError as exc:
        logger.warning("doctor_notification_calendar_failed", error=str(exc))
        return

    if not events:
        body = f"📅 Nenhuma consulta agendada para amanhã ({start.strftime('%d/%m')})."
    else:
        lines = [f"📅 Consultas de amanhã ({start.strftime('%d/%m')}):"]

        def _sort_key(e: dict[str, Any]) -> str:
            return e.get("start", {}).get("dateTime", "")

        for event in sorted(events, key=_sort_key):
            start_raw = event.get("start", {}).get("dateTime")
            if not start_raw:
                continue
            when = datetime.fromisoformat(start_raw).strftime("%H:%M")
            private = _event_private(event)
            patient = private.get("patient_name") or event.get("summary", "Consulta")
            lines.append(f"• {when} - {patient}")
        body = "\n".join(lines)

    try:
        await evolution.send_message(to=settings.doctor_whatsapp_number, body=body)
    except EvolutionSendError as exc:
        logger.warning("doctor_notification_send_failed", error=str(exc))
    else:
        logger.info("doctor_notification_sent", event_count=len(events))


async def send_patient_reminders(
    pool: AsyncConnectionPool, evolution: EvolutionClient
) -> None:
    """Envia lembrete de confirmação a cada paciente com consulta amanhã.

    Idempotente: usa a tabela `appointment_reminders` para nunca reenviar o
    mesmo evento — seguro de chamar mais de uma vez por dia (ex: após um
    restart do Worker).
    """
    start, end = _tomorrow_range()

    try:
        events = await list_events(start, end)
    except GoogleCalendarNotConfiguredError:
        return
    except HttpError as exc:
        logger.warning("patient_reminders_calendar_failed", error=str(exc))
        return

    for event in events:
        event_id = event.get("id")
        start_raw = event.get("start", {}).get("dateTime")
        if not event_id or not start_raw:
            continue

        private = _event_private(event)
        phone = private.get("phone")
        if not phone:
            continue

        async with pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM appointment_reminders WHERE event_id = %s",
                (event_id,),
            )
            already_sent = await cursor.fetchone()
        if already_sent:
            continue

        when = datetime.fromisoformat(start_raw)
        patient_name = private.get("patient_name") or "Paciente"
        body = (
            f"Olá, {patient_name}! Aqui é a secretária da Dra. Luana Lima 😊\n\n"
            "Passando para confirmar sua consulta de amanhã:\n\n"
            f"📅 Data: {when.strftime('%d/%m/%Y')}\n"
            f"⏰ Horário: {when.strftime('%H:%M')}\n"
            "👩‍⚕️ Dra. Luana Lima\n\n"
            "Nos vemos lá! Se precisar remarcar ou cancelar, é só me chamar por aqui."
        )

        try:
            await evolution.send_message(to=phone, body=body)
        except EvolutionSendError as exc:
            logger.warning(
                "patient_reminder_send_failed", event_id=event_id, error=str(exc)
            )
            continue

        async with pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO appointment_reminders
                    (event_id, phone_number, appointment_start)
                VALUES (%s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (event_id, phone, when),
            )
            await conn.commit()

        logger.info("patient_reminder_sent", event_id=event_id, phone=phone)
