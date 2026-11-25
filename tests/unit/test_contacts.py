"""Testes da rotina que mantém o @username dos contatos (best-effort)."""

from unittest.mock import AsyncMock, patch

import pytest

from whatsapp_langchain.worker.contacts import (
    backfill_contact_profiles,
    ensure_contact_profile,
)

MODULE = "whatsapp_langchain.worker.contacts"
IGSID = "17841400000000001"
PROFILE = {"username": "maria.silva", "name": "Maria", "profile_pic_url": "https://p"}


@pytest.fixture
def instagram():
    client = AsyncMock()
    client.get_user_profile.return_value = PROFILE
    return client


class TestEnsureContactProfile:
    async def test_fetches_and_saves_new_contact(self, instagram):
        with (
            patch(f"{MODULE}.needs_profile_refresh", return_value=True),
            patch(f"{MODULE}.upsert_contact") as upsert,
        ):
            assert await ensure_contact_profile(AsyncMock(), instagram, IGSID) is True

        instagram.get_user_profile.assert_awaited_once_with(IGSID)
        assert upsert.await_args.args[1] == IGSID
        assert upsert.await_args.kwargs == {
            "username": "maria.silva",
            "name": "Maria",
            "profile_pic_url": "https://p",
        }

    async def test_skips_fresh_profile_without_calling_api(self, instagram):
        with (
            patch(f"{MODULE}.needs_profile_refresh", return_value=False),
            patch(f"{MODULE}.upsert_contact") as upsert,
        ):
            assert await ensure_contact_profile(AsyncMock(), instagram, IGSID) is False

        instagram.get_user_profile.assert_not_awaited()
        upsert.assert_not_awaited()

    async def test_api_failure_saves_nothing(self, instagram):
        instagram.get_user_profile.return_value = None
        with (
            patch(f"{MODULE}.needs_profile_refresh", return_value=True),
            patch(f"{MODULE}.upsert_contact") as upsert,
        ):
            assert await ensure_contact_profile(AsyncMock(), instagram, IGSID) is False

        upsert.assert_not_awaited()

    async def test_database_error_never_propagates(self, instagram):
        with patch(f"{MODULE}.needs_profile_refresh", side_effect=RuntimeError("db")):
            assert await ensure_contact_profile(AsyncMock(), instagram, IGSID) is False


class TestBackfill:
    async def test_saves_each_pending_contact(self, instagram):
        with (
            patch(
                f"{MODULE}.list_contacts_without_profile", return_value=["1", "2", "3"]
            ),
            patch(f"{MODULE}.needs_profile_refresh", return_value=True),
            patch(f"{MODULE}.upsert_contact"),
        ):
            assert await backfill_contact_profiles(AsyncMock(), instagram) == 3

    async def test_query_failure_returns_zero(self, instagram):
        with patch(
            f"{MODULE}.list_contacts_without_profile", side_effect=RuntimeError("db")
        ):
            assert await backfill_contact_profiles(AsyncMock(), instagram) == 0
