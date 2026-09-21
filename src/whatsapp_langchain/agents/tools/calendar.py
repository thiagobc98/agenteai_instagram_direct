"""Ferramentas de agendamento via Google Calendar.

Disponibiliza:
- get_current_date: data/hora atual (necessária para o agente resolver
  expressões relativas como "hoje", "amanhã").
- check_availability: horários livres em uma data.
- book_appointment: cria uma nova consulta.
- reschedule_appointment: remarca a próxima consulta do paciente.
- cancel_appointment: cancela a próxima consulta do paciente.
- list_my_appointments: lista as consultas futuras do paciente.

Todas resolvem o ID do paciente (IGSID do Instagram) via `user_id` injetado no runtime
(ver agents/tools/_runtime.py) — o mesmo mecanismo usado pelas tools de
memória. O paciente é identificado pelo ID da conta no Instagram, não por nome.
"""

from datetime import datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import structlog
from googleapiclient.errors import HttpError
from langchain_core.tools import InjectedToolArg, tool

from whatsapp_langchain.agents.tools._runtime import extract_user_id
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.google_calendar import (
    GoogleCalendarNotConfiguredError,
    compute_free_slots,
    create_event,
    delete_event,
    find_events_by_external_id,
    get_busy_intervals,
    update_event,
)

logger = structlog.get_logger()

WEEKDAYS_PT = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]

_UNAVAILABLE_MSG = "Agendamento não está disponível neste momento."
_GENERIC_ERROR_MSG = (
    "Não consegui concluir essa operação de agenda agora. Podemos tentar de novo?"
)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.business_timezone)


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y %Hh%M").replace("h00", "h")


def _parse_date(date: str) -> tuple[datetime | None, str | None]:
    try:
        return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=_tz()), None
    except ValueError:
        return None, f"Data inválida: '{date}'. Use o formato AAAA-MM-DD."


def _parse_datetime(date: str, time: str) -> tuple[datetime | None, str | None]:
    day, error = _parse_date(date)
    if error:
        return None, error
    assert day is not None
    try:
        hour, minute = (int(part) for part in time.split(":"))
        return day.replace(hour=hour, minute=minute), None
    except (ValueError, AttributeError):
        return None, f"Horário inválido: '{time}'. Use o formato HH:MM."


@tool
async def get_current_date() -> str:
    """Retorna a data e hora atuais. Use antes de resolver datas relativas
    (hoje, amanhã, essa semana, etc.) para qualquer operação de agenda."""
    now = datetime.now(_tz())
    weekday = WEEKDAYS_PT[now.weekday()]
    return (
        f"Agora são {now.strftime('%H:%M')} de {weekday}, "
        f"{now.strftime('%d/%m/%Y')} (data ISO: {now.strftime('%Y-%m-%d')})."
    )


@tool
async def check_availability(date: str) -> str:
    """Lista os horários disponíveis para consulta em uma data.

    Args:
        date: Data no formato AAAA-MM-DD (use get_current_date para resolver
            datas relativas antes de chamar esta ferramenta).
    """
    day, error = _parse_date(date)
    if error:
        return error
    assert day is not None

    day_start = day.replace(hour=settings.business_hour_start, minute=0)
    day_end = day.replace(hour=settings.business_hour_end, minute=0)
    now = datetime.now(_tz())
    if day_start < now:
        day_start = now

    if day_start >= day_end:
        return "Não há mais horários disponíveis nesta data."

    try:
        busy = await get_busy_intervals(day_start, day_end)
    except GoogleCalendarNotConfiguredError:
        return _UNAVAILABLE_MSG
    except HttpError as exc:
        logger.warning("calendar_availability_failed", error=str(exc))
        return _GENERIC_ERROR_MSG

    slots = compute_free_slots(
        busy, day_start, day_end, settings.appointment_duration_minutes
    )
    if not slots:
        return f"Não há horários livres em {day.strftime('%d/%m/%Y')}."

    times = ", ".join(slot.strftime("%H:%M") for slot in slots)
    return f"Horários disponíveis em {day.strftime('%d/%m/%Y')}: {times}."


@tool
async def book_appointment(
    patient_name: str,
    date: str,
    time: str,
    notes: str = "",
    *,
    runtime: Annotated[Any, InjectedToolArg()] = None,
) -> str:
    """Agenda uma nova consulta, se o horário estiver livre.

    Sempre confirme o horário com o paciente antes de chamar esta ferramenta
    (ela cria o evento imediatamente, sem outra confirmação).

    Args:
        patient_name: Nome do paciente.
        date: Data da consulta no formato AAAA-MM-DD.
        time: Horário no formato HH:MM.
        notes: Observações opcionais sobre a consulta.
    """
    external_id, error = extract_user_id(runtime)
    if error:
        return error

    start, error = _parse_datetime(date, time)
    if error:
        return error
    assert start is not None
    end = start + timedelta(minutes=settings.appointment_duration_minutes)

    try:
        busy = await get_busy_intervals(start, end)
        if busy:
            return (
                f"O horário {_format_dt(start)} não está disponível. "
                "Consulte check_availability para ver outras opções."
            )

        await create_event(
            summary=f"Consulta - {patient_name}",
            description=notes,
            start=start,
            end=end,
            external_id=external_id,  # type: ignore[arg-type]
            patient_name=patient_name,
        )
    except GoogleCalendarNotConfiguredError:
        return _UNAVAILABLE_MSG
    except HttpError as exc:
        logger.warning("calendar_book_failed", error=str(exc), external_id=external_id)
        return _GENERIC_ERROR_MSG

    return f"Consulta agendada com sucesso! 📅 {_format_dt(start)}"


@tool
async def reschedule_appointment(
    new_date: str,
    new_time: str,
    *,
    runtime: Annotated[Any, InjectedToolArg()] = None,
) -> str:
    """Remarca a próxima consulta do paciente para uma nova data/horário.

    Sempre confirme o novo horário com o paciente antes de chamar esta
    ferramenta. Age sobre a consulta futura mais próxima do paciente.

    Args:
        new_date: Nova data no formato AAAA-MM-DD.
        new_time: Novo horário no formato HH:MM.
    """
    external_id, error = extract_user_id(runtime)
    if error:
        return error

    new_start, error = _parse_datetime(new_date, new_time)
    if error:
        return error
    assert new_start is not None
    new_end = new_start + timedelta(minutes=settings.appointment_duration_minutes)

    try:
        events = await find_events_by_external_id(external_id)  # type: ignore[arg-type]
        if not events:
            return "Não encontrei nenhuma consulta futura para remarcar."

        busy = await get_busy_intervals(new_start, new_end)
        if busy:
            return (
                f"O horário {_format_dt(new_start)} não está disponível. "
                "Consulte check_availability para ver outras opções."
            )

        await update_event(events[0]["id"], start=new_start, end=new_end)
    except GoogleCalendarNotConfiguredError:
        return _UNAVAILABLE_MSG
    except HttpError as exc:
        logger.warning(
            "calendar_reschedule_failed", error=str(exc), external_id=external_id
        )
        return _GENERIC_ERROR_MSG

    return f"Consulta remarcada com sucesso para {_format_dt(new_start)}."


@tool
async def cancel_appointment(
    *,
    runtime: Annotated[Any, InjectedToolArg()] = None,
) -> str:
    """Cancela a próxima consulta futura do paciente.

    Sempre confirme com o paciente qual consulta ele deseja cancelar antes
    de chamar esta ferramenta.
    """
    external_id, error = extract_user_id(runtime)
    if error:
        return error

    try:
        events = await find_events_by_external_id(external_id)  # type: ignore[arg-type]
        if not events:
            return "Não encontrei nenhuma consulta futura para cancelar."

        target = events[0]
        await delete_event(target["id"])
    except GoogleCalendarNotConfiguredError:
        return _UNAVAILABLE_MSG
    except HttpError as exc:
        logger.warning(
            "calendar_cancel_failed", error=str(exc), external_id=external_id
        )
        return _GENERIC_ERROR_MSG

    start_raw = target["start"].get("dateTime")
    when = _format_dt(datetime.fromisoformat(start_raw)) if start_raw else ""
    return f"Consulta{' de ' + when if when else ''} cancelada com sucesso."


@tool
async def list_my_appointments(
    *,
    runtime: Annotated[Any, InjectedToolArg()] = None,
) -> str:
    """Lista as próximas consultas futuras já agendadas para o paciente."""
    external_id, error = extract_user_id(runtime)
    if error:
        return error

    try:
        events = await find_events_by_external_id(external_id)  # type: ignore[arg-type]
    except GoogleCalendarNotConfiguredError:
        return _UNAVAILABLE_MSG
    except HttpError as exc:
        logger.warning("calendar_list_failed", error=str(exc), external_id=external_id)
        return _GENERIC_ERROR_MSG

    if not events:
        return "Você não tem nenhuma consulta agendada."

    lines = ["Suas próximas consultas:"]
    for event in events:
        start_raw = event["start"].get("dateTime")
        if not start_raw:
            continue
        lines.append(f"- {_format_dt(datetime.fromisoformat(start_raw))}")
    return "\n".join(lines)
