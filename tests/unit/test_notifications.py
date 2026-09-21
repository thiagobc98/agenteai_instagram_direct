"""Testes para notificações proativas (worker/notifications.py).

Cobre a agenda enviada à médica e o lembrete diário enviado aos pacientes com
consulta no dia seguinte — incluindo a regra da janela de 24h do Instagram
(só é possível enviar a quem escreveu para a conta nas últimas 24h).
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.worker.instagram_client import InstagramSendError
from whatsapp_langchain.worker.notifications import (
    _tomorrow_range,
    notify_doctor_tomorrow_schedule,
    send_patient_reminders,
)

MODULE = "whatsapp_langchain.worker.notifications"
TZ = ZoneInfo("America/Sao_Paulo")
DOCTOR_ID = "17841400000000001"
PATIENT_ID = "17841400000000002"


def _event(
    event_id: str,
    start: datetime,
    *,
    external_id: str | None = None,
    name: str | None = None,
):
    return {
        "id": event_id,
        "summary": f"Consulta - {name}" if name else "Consulta",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=30)).isoformat()},
        "extendedProperties": {
            "private": {"external_id": external_id, "patient_name": name}
        },
    }


def _within_window():
    """Último contato há 2h — dentro da janela de 24h."""
    return patch(
        f"{MODULE}.get_last_inbound_at",
        new=AsyncMock(return_value=datetime.now(UTC) - timedelta(hours=2)),
    )


def _outside_window():
    """Último contato há 30h — fora da janela de 24h."""
    return patch(
        f"{MODULE}.get_last_inbound_at",
        new=AsyncMock(return_value=datetime.now(UTC) - timedelta(hours=30)),
    )


def _never_wrote():
    return patch(f"{MODULE}.get_last_inbound_at", new=AsyncMock(return_value=None))


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
    def test_skips_when_doctor_id_not_configured(self, mock_pool):
        pool, _ = mock_pool
        instagram = AsyncMock()
        with patch.object(settings, "doctor_instagram_id", ""):
            asyncio.run(notify_doctor_tomorrow_schedule(pool, instagram))
        instagram.send_message.assert_not_called()

    def test_sends_empty_agenda_message(self, mock_pool):
        pool, _ = mock_pool
        instagram = AsyncMock()
        with (
            patch.object(settings, "doctor_instagram_id", DOCTOR_ID),
            _within_window(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[])),
        ):
            asyncio.run(notify_doctor_tomorrow_schedule(pool, instagram))
        instagram.send_message.assert_called_once()
        body = instagram.send_message.call_args.kwargs["body"]
        assert "nenhuma consulta" in body.lower()

    def test_sends_sorted_agenda(self, mock_pool):
        pool, _ = mock_pool
        instagram = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        late = _event("evt-late", base.replace(hour=16, minute=0), name="Carlos")
        early = _event("evt-early", base.replace(hour=9, minute=0), name="Ana")
        with (
            patch.object(settings, "doctor_instagram_id", DOCTOR_ID),
            _within_window(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[late, early])),
        ):
            asyncio.run(notify_doctor_tomorrow_schedule(pool, instagram))
        body = instagram.send_message.call_args.kwargs["body"]
        assert body.index("Ana") < body.index("Carlos")
        assert instagram.send_message.call_args.kwargs["to"] == DOCTOR_ID

    def test_swallows_send_error(self, mock_pool):
        pool, _ = mock_pool
        instagram = AsyncMock()
        instagram.send_message.side_effect = InstagramSendError(500, "boom")
        with (
            patch.object(settings, "doctor_instagram_id", DOCTOR_ID),
            _within_window(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[])),
        ):
            # Não deve propagar exceção
            asyncio.run(notify_doctor_tomorrow_schedule(pool, instagram))

    def test_skips_outside_24h_window_without_calling_calendar(self, mock_pool):
        pool, _ = mock_pool
        instagram = AsyncMock()
        list_events = AsyncMock(return_value=[])
        with (
            patch.object(settings, "doctor_instagram_id", DOCTOR_ID),
            _outside_window(),
            patch(f"{MODULE}.list_events", new=list_events),
            patch(f"{MODULE}.logger.warning") as mock_warning,
        ):
            asyncio.run(notify_doctor_tomorrow_schedule(pool, instagram))

        instagram.send_message.assert_not_called()
        list_events.assert_not_called()
        assert (
            mock_warning.call_args.args[0]
            == "doctor_notification_skipped_outside_window"
        )

    def test_skips_when_doctor_never_wrote(self, mock_pool):
        pool, _ = mock_pool
        instagram = AsyncMock()
        with (
            patch.object(settings, "doctor_instagram_id", DOCTOR_ID),
            _never_wrote(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[])),
        ):
            asyncio.run(notify_doctor_tomorrow_schedule(pool, instagram))
        instagram.send_message.assert_not_called()

    def test_window_check_failure_does_not_propagate(self, mock_pool):
        pool, _ = mock_pool
        instagram = AsyncMock()
        with (
            patch.object(settings, "doctor_instagram_id", DOCTOR_ID),
            patch(
                f"{MODULE}.get_last_inbound_at",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            asyncio.run(notify_doctor_tomorrow_schedule(pool, instagram))
        instagram.send_message.assert_not_called()


class TestSendPatientReminders:
    def test_skips_event_without_external_id(self, mock_pool):
        pool, conn = mock_pool
        instagram = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event("evt1", base.replace(hour=10), external_id=None, name="Sem ID")

        with patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])):
            asyncio.run(send_patient_reminders(pool, instagram))

        instagram.send_message.assert_not_called()
        conn.execute.assert_not_called()

    def test_skips_legacy_whatsapp_event_with_phone_key(self, mock_pool):
        """Eventos antigos guardavam o telefone em `phone` — não são IGSIDs."""
        pool, conn = mock_pool
        instagram = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event("evt1", base.replace(hour=10), name="Antigo")
        event["extendedProperties"]["private"] = {
            "phone": "+5511999999999",
            "patient_name": "Antigo",
        }

        with patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])):
            asyncio.run(send_patient_reminders(pool, instagram))

        instagram.send_message.assert_not_called()

    def test_skips_already_reminded_event(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=(1,))
        conn.execute = AsyncMock(return_value=select_cursor)

        instagram = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event(
            "evt1", base.replace(hour=10), external_id=PATIENT_ID, name="Maria"
        )

        with (
            _within_window(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])),
        ):
            asyncio.run(send_patient_reminders(pool, instagram))

        instagram.send_message.assert_not_called()

    def test_sends_reminder_and_records_it(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=None)
        insert_cursor = AsyncMock()
        conn.execute = AsyncMock(side_effect=[select_cursor, insert_cursor])

        instagram = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event(
            "evt1", base.replace(hour=10), external_id=PATIENT_ID, name="Maria"
        )

        with (
            _within_window(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])),
        ):
            asyncio.run(send_patient_reminders(pool, instagram))

        instagram.send_message.assert_called_once()
        assert instagram.send_message.call_args.kwargs["to"] == PATIENT_ID
        body = instagram.send_message.call_args.kwargs["body"]
        assert "Maria" in body
        conn.commit.assert_called_once()

    def test_send_failure_does_not_record_and_continues(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=select_cursor)

        instagram = AsyncMock()
        instagram.send_message.side_effect = InstagramSendError(500, "boom")
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event(
            "evt1", base.replace(hour=10), external_id=PATIENT_ID, name="Maria"
        )

        with (
            _within_window(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])),
        ):
            # Não deve propagar exceção
            asyncio.run(send_patient_reminders(pool, instagram))

        conn.commit.assert_not_called()

    def test_outside_window_is_skipped_logged_and_not_recorded(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=select_cursor)

        instagram = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        event = _event(
            "evt1", base.replace(hour=10), external_id=PATIENT_ID, name="Maria"
        )

        with (
            _outside_window(),
            patch(f"{MODULE}.list_events", new=AsyncMock(return_value=[event])),
            patch(f"{MODULE}.logger.warning") as mock_warning,
        ):
            asyncio.run(send_patient_reminders(pool, instagram))

        instagram.send_message.assert_not_called()
        # Não marca como lembrado: uma nova execução pode tentar de novo.
        conn.commit.assert_not_called()
        assert (
            mock_warning.call_args.args[0] == "patient_reminder_skipped_outside_window"
        )
        assert mock_warning.call_args.kwargs["event_id"] == "evt1"

    def test_only_patients_inside_window_are_reminded(self, mock_pool):
        pool, conn = mock_pool
        select_cursor = AsyncMock()
        select_cursor.fetchone = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=select_cursor)

        instagram = AsyncMock()
        base = datetime.now(TZ) + timedelta(days=1)
        inside = _event("evt-in", base.replace(hour=9), external_id="111", name="Ana")
        outside = _event(
            "evt-out", base.replace(hour=10), external_id="222", name="Bia"
        )

        async def last_inbound(pool, external_id):
            hours = 2 if external_id == "111" else 40
            return datetime.now(UTC) - timedelta(hours=hours)

        with (
            patch(f"{MODULE}.get_last_inbound_at", new=last_inbound),
            patch(
                f"{MODULE}.list_events", new=AsyncMock(return_value=[inside, outside])
            ),
        ):
            asyncio.run(send_patient_reminders(pool, instagram))

        instagram.send_message.assert_called_once()
        assert instagram.send_message.call_args.kwargs["to"] == "111"
