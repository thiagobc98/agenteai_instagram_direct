"""Cliente Google Calendar (Service Account) e cálculo de horários livres.

Autenticação via Service Account: a agenda de destino precisa estar
compartilhada com o e-mail da service account (permissão "fazer alterações
em eventos"). Não há fluxo de consentimento OAuth — nenhuma interação do
usuário final é necessária.

A biblioteca google-api-python-client é síncrona; todas as chamadas de rede
são executadas em thread separada via `asyncio.to_thread` para não bloquear
o event loop do worker.

Uso:
    from whatsapp_langchain.shared.google_calendar import (
        create_event, update_event, delete_event, find_events_by_phone,
        get_busy_intervals, compute_free_slots,
    )
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build

from whatsapp_langchain.shared.config import settings

logger = structlog.get_logger()

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# O client da Calendar API (via _build_service, cacheado) reusa uma única
# conexão HTTP (httplib2) por baixo do googleapiclient — não é thread-safe
# para chamadas concorrentes. Duas requisições simultâneas (ex: os dois
# cards do Dashboard carregando ao mesmo tempo) corrompem a conexão
# compartilhada. Este lock serializa todas as chamadas de rede à API.
_CALENDAR_LOCK = asyncio.Lock()


class GoogleCalendarNotConfiguredError(Exception):
    """Erro quando a integração com Google Calendar não está configurada."""


@lru_cache(maxsize=1)
def _build_service() -> Any:
    # googleapiclient.discovery.Resource é um proxy dinâmico gerado a partir
    # do discovery document da API — não tem os métodos (events(),
    # freebusy()) conhecidos estaticamente, por isso o retorno é Any.
    """Constrói (e cacheia) o client da Calendar API a partir da service account."""
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
    elif settings.google_service_account_file:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=SCOPES
        )
    else:
        raise GoogleCalendarNotConfiguredError(
            "Configure GOOGLE_SERVICE_ACCOUNT_JSON ou GOOGLE_SERVICE_ACCOUNT_FILE."
        )

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _calendar_id() -> str:
    if not settings.google_calendar_id:
        raise GoogleCalendarNotConfiguredError("Configure GOOGLE_CALENDAR_ID.")
    return settings.google_calendar_id


def _event_body(
    *,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    phone: str,
    patient_name: str,
) -> dict[str, Any]:
    tz = settings.business_timezone
    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": tz},
        "end": {"dateTime": end.isoformat(), "timeZone": tz},
        "extendedProperties": {
            "private": {"phone": phone, "patient_name": patient_name}
        },
    }


async def get_busy_intervals(
    time_min: datetime, time_max: datetime
) -> list[tuple[datetime, datetime]]:
    """Retorna os intervalos ocupados do calendário entre time_min e time_max."""

    def _call() -> dict:
        service = _build_service()
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": _calendar_id()}],
        }
        return service.freebusy().query(body=body).execute()

    async with _CALENDAR_LOCK:
        result = await asyncio.to_thread(_call)
    calendars = result.get("calendars", {})
    busy_raw = calendars.get(_calendar_id(), {}).get("busy", [])

    intervals = []
    for item in busy_raw:
        start = datetime.fromisoformat(item["start"])
        end = datetime.fromisoformat(item["end"])
        intervals.append((start, end))
    return intervals


def compute_free_slots(
    busy: list[tuple[datetime, datetime]],
    day_start: datetime,
    day_end: datetime,
    slot_minutes: int,
) -> list[datetime]:
    """Calcula os horários de início livres entre day_start e day_end.

    Função pura (sem I/O) — cada candidato de slot [t, t+slot_minutes) é
    aceito se não sobrepõe nenhum intervalo em `busy`. Todos os datetimes
    devem estar no mesmo fuso horário (aware).
    """
    slots: list[datetime] = []
    step = timedelta(minutes=slot_minutes)
    duration = timedelta(minutes=slot_minutes)

    candidate = day_start
    while candidate + duration <= day_end:
        candidate_end = candidate + duration
        overlaps = any(
            candidate < busy_end and candidate_end > busy_start
            for busy_start, busy_end in busy
        )
        if not overlaps:
            slots.append(candidate)
        candidate += step

    return slots


async def create_event(
    *,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    phone: str,
    patient_name: str,
) -> dict[str, Any]:
    """Cria um evento na agenda e retorna o evento criado (com `id`)."""
    body = _event_body(
        summary=summary,
        description=description,
        start=start,
        end=end,
        phone=phone,
        patient_name=patient_name,
    )

    def _call() -> dict:
        service = _build_service()
        return service.events().insert(calendarId=_calendar_id(), body=body).execute()

    async with _CALENDAR_LOCK:
        event = await asyncio.to_thread(_call)
    logger.info("calendar_event_created", event_id=event.get("id"), phone=phone)
    return event


async def update_event(
    event_id: str, *, start: datetime, end: datetime
) -> dict[str, Any]:
    """Atualiza o horário (start/end) de um evento existente."""
    tz = settings.business_timezone

    def _call() -> dict:
        service = _build_service()
        patch = {
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
        }
        return (
            service.events()
            .patch(calendarId=_calendar_id(), eventId=event_id, body=patch)
            .execute()
        )

    async with _CALENDAR_LOCK:
        event = await asyncio.to_thread(_call)
    logger.info("calendar_event_updated", event_id=event_id)
    return event


async def delete_event(event_id: str) -> None:
    """Cancela (remove) um evento da agenda."""

    def _call() -> None:
        service = _build_service()
        service.events().delete(calendarId=_calendar_id(), eventId=event_id).execute()

    async with _CALENDAR_LOCK:
        await asyncio.to_thread(_call)
    logger.info("calendar_event_deleted", event_id=event_id)


async def list_events(time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
    """Lista todos os eventos do calendário entre time_min e time_max.

    Usado pela página de Agenda do painel admin (visão semanal).
    """

    def _call() -> dict:
        service = _build_service()
        return (
            service.events()
            .list(
                calendarId=_calendar_id(),
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )

    async with _CALENDAR_LOCK:
        result = await asyncio.to_thread(_call)
    return [
        event for event in result.get("items", []) if event.get("status") != "cancelled"
    ]


async def find_events_by_phone(
    phone: str, *, time_min: datetime | None = None
) -> list[dict[str, Any]]:
    """Lista os próximos eventos futuros marcados com o telefone informado."""
    time_min = time_min or datetime.now().astimezone()

    def _call() -> dict:
        service = _build_service()
        return (
            service.events()
            .list(
                calendarId=_calendar_id(),
                privateExtendedProperty=f"phone={phone}",
                timeMin=time_min.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            )
            .execute()
        )

    async with _CALENDAR_LOCK:
        result = await asyncio.to_thread(_call)
    return [
        event for event in result.get("items", []) if event.get("status") != "cancelled"
    ]
