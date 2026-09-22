"""Testes de shared/contacts.py: leitura do @ salvo de um contato."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from whatsapp_langchain.shared.contacts import get_contact_username


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
