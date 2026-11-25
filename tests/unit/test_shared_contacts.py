"""Testes de shared/contacts.py: @ e WhatsApp salvos de um contato."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from whatsapp_langchain.shared.contacts import (
    get_contact_username,
    get_customer_whatsapp,
    normalize_whatsapp,
    set_customer_whatsapp,
)


@pytest.fixture
def mock_pool():
    """Pool mockado com conexão fake via asynccontextmanager.

    Retorna (pool, conn) para inspeção do SQL executado.
    """
    conn = AsyncMock()
    pool = AsyncMock()

    @asynccontextmanager
    async def fake_connection():
        yield conn

    pool.connection = fake_connection
    return pool, conn


class TestGetContactUsername:
    async def test_returns_the_saved_username(self, mock_pool):
        pool, conn = mock_pool
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=("_thibec",))
        conn.execute = AsyncMock(return_value=cursor)

        result = await get_contact_username(pool, "17841400000000001")

        assert result == "_thibec"
        sql, params = conn.execute.call_args.args
        assert "SELECT username FROM contacts" in sql
        assert params == ("17841400000000001",)

    async def test_returns_none_when_username_is_null(self, mock_pool):
        pool, conn = mock_pool
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(None,))
        conn.execute = AsyncMock(return_value=cursor)

        assert await get_contact_username(pool, "17841400000000001") is None

    async def test_returns_none_when_contact_does_not_exist(self, mock_pool):
        pool, conn = mock_pool
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=cursor)

        assert await get_contact_username(pool, "17841400000000001") is None


class TestNormalizeWhatsapp:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("31999998888", "5531999998888"),
            ("(31) 99999-8888", "5531999998888"),
            ("31 99999-8888", "5531999998888"),
            ("+55 31 99999-8888", "5531999998888"),
            ("5531999998888", "5531999998888"),
            ("55 (31) 99999-8888", "5531999998888"),
            ("3199998888", "553199998888"),  # DDD + fixo (8 dígitos)
            ("031999998888", "5531999998888"),  # zero inicial descartado
        ],
    )
    def test_normalizes_common_formats(self, raw, expected):
        assert normalize_whatsapp(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["abc", "", "123", "999998888", "12345678901234", "9"],
    )
    def test_rejects_things_that_are_not_a_phone_number(self, raw):
        assert normalize_whatsapp(raw) is None


class TestSetCustomerWhatsapp:
    async def test_upserts_only_the_whatsapp_column(self, mock_pool):
        pool, conn = mock_pool
        conn.execute = AsyncMock()

        await set_customer_whatsapp(pool, "17841400000000001", whatsapp="5531999998888")

        sql, params = conn.execute.call_args.args
        assert "INSERT INTO contacts" in sql
        assert "ON CONFLICT (external_id) DO UPDATE SET whatsapp" in sql
        assert params == ("17841400000000001", "5531999998888")
        conn.commit.assert_awaited_once()


class TestGetCustomerWhatsapp:
    async def test_returns_the_saved_number(self, mock_pool):
        pool, conn = mock_pool
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=("5531999998888",))
        conn.execute = AsyncMock(return_value=cursor)

        result = await get_customer_whatsapp(pool, "17841400000000001")

        assert result == "5531999998888"
        sql, params = conn.execute.call_args.args
        assert "SELECT whatsapp FROM contacts" in sql
        assert params == ("17841400000000001",)

    async def test_returns_none_when_not_saved_yet(self, mock_pool):
        pool, conn = mock_pool
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(None,))
        conn.execute = AsyncMock(return_value=cursor)

        assert await get_customer_whatsapp(pool, "17841400000000001") is None
