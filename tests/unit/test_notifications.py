"""Testes para notificações proativas (worker/notifications.py).

Cobre a agenda enviada à médica (a cada agendamento/remarcação/cancelamento)
e o lembrete diário enviado aos pacientes com consulta no dia seguinte.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.worker.evolution_client import EvolutionSendError
from whatsapp_langchain.worker.notifications import (
    _tomorrow_range,
    notify_doctor_tomorrow_schedule,
    send_patient_reminders,
)

MODULE = "whatsapp_langchain.worker.notifications"
TZ = ZoneInfo("America/Sao_Paulo")


def _event(
    event_id: str, start: datetime, *, phone: str | None = None, name: str | None = None
):
    return {
        "id": event_id,
        "summary": f"Consulta - {name}" if name else "Consulta",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=30)).isoformat()},
        "extendedProperties": {"private": {"phone": phone, "patient_name": name}},
    }


@pytest.fixture
def mock_pool():
    conn = AsyncMock()

    @asynccontextmanager
    async def fake_connection():
        yield conn

    pool = AsyncMock()
    pool.connection = fake_connection
    return pool, conn


class TestTomorrowRange:
    def test_returns_full_day_after_now(self):
        now = datetime(2026, 9, 14, 15, 30, tzinfo=TZ)
        start, end = _tomorrow_range(now)
        assert start == datetime(2026, 9, 15, 0, 0, tzinfo=TZ)
        assert end == datetime(2026, 9, 16, 0, 0, tzinfo=TZ)


class TestNotifyDoctorTomorrowSchedule:
    def test_skips_when_doctor_number_not_configured(self):
        evolution = AsyncMock()
        with patch.object(settings, "doctor_whatsapp_number", ""):
            asyncio.run(notify_doctor_tomorrow_schedule(evolution))
        evolution.send_message.assert_not_called()

    def test_sends_empty_agenda_message(self):
        evolution = AsyncMock()
        with (
            patch.object(settings, "doctor_whatsapp_number", "+5531900000000"),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[])),
        ):
            asyncio.run(notify_doctor_tomorrow_schedule(evolution))
        evolution.send_message.assert_called_once()
        body = evolution.send_message.call_args.kwargs["body"]
        assert "nenhuma consulta" in body.lower()

    def test_sends_sorted_agenda(self):
        evolution = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        late = _event("evt-late", base.replace(hour=16, minute=0), name="Carlos")
        early = _event("evt-early", base.replace(hour=9, minute=0), name="Ana")
        with (
            patch.object(settings, "doctor_whatsapp_number", "+5531900000000"),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[late, early])),
        ):
            asyncio.run(notify_doctor_tomorrow_schedule(evolution))
        body = evolution.send_message.call_args.kwargs["body"]
        assert body.index("Ana") < body.index("Carlos")
        assert evolution.send_message.call_args.kwargs["to"] == "+5531900000000"

    def test_swallows_send_error(self):
        evolution = AsyncMock()
        evolution.send_message.side_effect = EvolutionSendError(500, "boom")
        with (
            patch.object(settings, "doctor_whatsapp_number", "+5531900000000"),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[])),
        ):
            # Não deve propagar exceção
            asyncio.run(notify_doctor_tomorrow_schedule(evolution))


class TestSendPatientReminders:
    def test_skips_event_without_phone(self, mock_pool):
        pool, conn = mock_pool
        evolution = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event("evt1", base.replace(hour=10), phone=None, name="Sem telefone")

        with patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])):
            asyncio.run(send_patient_reminders(pool, evolution))

        evolution.send_message.assert_not_called()
        conn.execute.assert_not_called()

    def test_skips_already_reminded_event(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=(1,))
        conn.execute = AsyncMock(return_value=select_cursor)

        evolution = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event(
            "evt1", base.replace(hour=10), phone="+5511999999999", name="Maria"
        )

        with patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])):
            asyncio.run(send_patient_reminders(pool, evolution))

        evolution.send_message.assert_not_called()

    def test_sends_reminder_and_records_it(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=None)
        insert_cursor = AsyncMock()
        conn.execute = AsyncMock(side_effect=[select_cursor, insert_cursor])

        evolution = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event(
            "evt1", base.replace(hour=10), phone="+5511999999999", name="Maria"
        )

        with patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])):
            asyncio.run(send_patient_reminders(pool, evolution))

        evolution.send_message.assert_called_once()
        assert evolution.send_message.call_args.kwargs["to"] == "+5511999999999"
        body = evolution.send_message.call_args.kwargs["body"]
        assert "Maria" in body
        conn.commit.assert_called_once()

    def test_send_failure_does_not_record_and_continues(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=select_cursor)

        evolution = AsyncMock()
        evolution.send_message.side_effect = EvolutionSendError(500, "boom")
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event(
            "evt1", base.replace(hour=10), phone="+5511999999999", name="Maria"
        )

        with patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])):
            # Não deve propagar exceção
            asyncio.run(send_patient_reminders(pool, evolution))

        conn.commit.assert_not_called()
