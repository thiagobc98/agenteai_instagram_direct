"""Testes para as tools de agendamento (Google Calendar)."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from whatsapp_langchain.agents.tools.calendar import (
    book_appointment,
    cancel_appointment,
    check_availability,
    list_my_appointments,
    reschedule_appointment,
)
from whatsapp_langchain.shared.google_calendar import compute_free_slots

book_fn = book_appointment.coroutine
reschedule_fn = reschedule_appointment.coroutine
cancel_fn = cancel_appointment.coroutine
list_fn = list_my_appointments.coroutine
check_fn = check_availability.coroutine

TZ = ZoneInfo("America/Sao_Paulo")
MODULE = "whatsapp_langchain.agents.tools.calendar"


def _make_runtime(*, user_id: str | None = "17841400000000001"):
    configurable = {"thread_id": "thread-test"}
    if user_id:
        configurable["user_id"] = user_id
    runtime = MagicMock()
    runtime.config = {"configurable": configurable}
    return runtime


def _future_date() -> str:
    return (datetime.now(TZ) + timedelta(days=7)).strftime("%Y-%m-%d")


def _event(event_id: str, start: datetime) -> dict:
    return {
        "id": event_id,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=30)).isoformat()},
    }


class TestComputeFreeSlots:
    """Função pura de cálculo de horários livres."""

    def test_no_busy_returns_all_slots(self):
        start = datetime(2026, 1, 5, 9, 0, tzinfo=TZ)
        end = datetime(2026, 1, 5, 10, 0, tzinfo=TZ)
        slots = compute_free_slots([], start, end, 30)
        assert slots == [start, start + timedelta(minutes=30)]

    def test_busy_interval_blocks_overlapping_slot(self):
        start = datetime(2026, 1, 5, 9, 0, tzinfo=TZ)
        end = datetime(2026, 1, 5, 10, 0, tzinfo=TZ)
        busy = [
            (
                datetime(2026, 1, 5, 9, 0, tzinfo=TZ),
                datetime(2026, 1, 5, 9, 30, tzinfo=TZ),
            )
        ]
        slots = compute_free_slots(busy, start, end, 30)
        assert slots == [start + timedelta(minutes=30)]

    def test_busy_interval_partially_overlapping_still_blocks(self):
        start = datetime(2026, 1, 5, 9, 0, tzinfo=TZ)
        end = datetime(2026, 1, 5, 10, 0, tzinfo=TZ)
        busy = [
            (
                datetime(2026, 1, 5, 9, 15, tzinfo=TZ),
                datetime(2026, 1, 5, 9, 45, tzinfo=TZ),
            )
        ]
        slots = compute_free_slots(busy, start, end, 30)
        assert slots == []


class TestCheckAvailability:
    def test_invalid_date_returns_error(self):
        result = asyncio.run(check_fn("not-a-date"))
        assert "inválida" in result.lower()

    def test_lists_free_slots(self):
        with patch(f"{MODULE}.get_busy_intervals", new=AsyncMock(return_value=[])):
            result = asyncio.run(check_fn(_future_date()))
        assert "disponíveis" in result.lower()
        assert ":" in result


class TestBookAppointment:
    def test_returns_error_when_user_missing(self):
        runtime = _make_runtime(user_id=None)
        result = asyncio.run(book_fn("Maria", _future_date(), "14:00", runtime=runtime))
        assert "user_id" in result.lower()

    def test_books_when_slot_free(self):
        runtime = _make_runtime()
        create_mock = AsyncMock(return_value={"id": "evt1"})
        with (
            patch(f"{MODULE}.get_busy_intervals", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.create_event", new=create_mock),
        ):
            result = asyncio.run(
                book_fn("Maria", _future_date(), "14:00", runtime=runtime)
            )
        assert "agendada com sucesso" in result.lower()
        create_mock.assert_called_once()
        assert create_mock.call_args.kwargs["patient_name"] == "Maria"
        assert create_mock.call_args.kwargs["external_id"] == "17841400000000001"

    def test_rejects_when_slot_busy(self):
        runtime = _make_runtime()
        create_mock = AsyncMock()
        busy = [(datetime.now(TZ), datetime.now(TZ) + timedelta(minutes=30))]
        with (
            patch(f"{MODULE}.get_busy_intervals", new=AsyncMock(return_value=busy)),
            patch(f"{MODULE}.create_event", new=create_mock),
        ):
            result = asyncio.run(
                book_fn("Maria", _future_date(), "14:00", runtime=runtime)
            )
        assert "não está disponível" in result.lower()
        create_mock.assert_not_called()

    def test_invalid_time_returns_error(self):
        runtime = _make_runtime()
        result = asyncio.run(book_fn("Maria", _future_date(), "25:99", runtime=runtime))
        assert "inválido" in result.lower()


class TestRescheduleAppointment:
    def test_returns_message_when_no_appointment(self):
        runtime = _make_runtime()
        with patch(
            f"{MODULE}.find_events_by_external_id", new=AsyncMock(return_value=[])
        ):
            result = asyncio.run(
                reschedule_fn(_future_date(), "15:00", runtime=runtime)
            )
        assert "não encontrei" in result.lower()

    def test_reschedules_nearest_event(self):
        runtime = _make_runtime()
        existing = _event("evt1", datetime.now(TZ) + timedelta(days=1))
        update_mock = AsyncMock()
        with (
            patch(
                f"{MODULE}.find_events_by_external_id",
                new=AsyncMock(return_value=[existing]),
            ),
            patch(f"{MODULE}.get_busy_intervals", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.update_event", new=update_mock),
        ):
            result = asyncio.run(
                reschedule_fn(_future_date(), "15:00", runtime=runtime)
            )
        assert "remarcada com sucesso" in result.lower()
        update_mock.assert_called_once()
        assert update_mock.call_args.args[0] == "evt1"


class TestCancelAppointment:
    def test_returns_message_when_no_appointment(self):
        runtime = _make_runtime()
        with patch(
            f"{MODULE}.find_events_by_external_id", new=AsyncMock(return_value=[])
        ):
            result = asyncio.run(cancel_fn(runtime=runtime))
        assert "não encontrei" in result.lower()

    def test_cancels_nearest_event(self):
        runtime = _make_runtime()
        existing = _event("evt1", datetime.now(TZ) + timedelta(days=1))
        delete_mock = AsyncMock()
        with (
            patch(
                f"{MODULE}.find_events_by_external_id",
                new=AsyncMock(return_value=[existing]),
            ),
            patch(f"{MODULE}.delete_event", new=delete_mock),
        ):
            result = asyncio.run(cancel_fn(runtime=runtime))
        assert "cancelada com sucesso" in result.lower()
        delete_mock.assert_called_once_with("evt1")


class TestListMyAppointments:
    def test_returns_message_when_empty(self):
        runtime = _make_runtime()
        with patch(
            f"{MODULE}.find_events_by_external_id", new=AsyncMock(return_value=[])
        ):
            result = asyncio.run(list_fn(runtime=runtime))
        assert "não tem nenhuma consulta" in result.lower()

    def test_lists_events(self):
        runtime = _make_runtime()
        existing = _event("evt1", datetime.now(TZ) + timedelta(days=1))
        with patch(
            f"{MODULE}.find_events_by_external_id",
            new=AsyncMock(return_value=[existing]),
        ):
            result = asyncio.run(list_fn(runtime=runtime))
        assert "próximas consultas" in result.lower()
