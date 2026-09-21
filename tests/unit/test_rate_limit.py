"""Testes do rate limiter distribuído (Redis)."""

import time
from unittest.mock import patch

import fakeredis
import pytest
from fastapi import HTTPException

from whatsapp_langchain.server.dependencies import check_rate_limit


@pytest.fixture(autouse=True)
def fake_redis():
    """Redis em memória (fakeredis), isolado por teste."""
    redis = fakeredis.FakeAsyncRedis()
    with patch(
        "whatsapp_langchain.server.dependencies.get_redis",
        return_value=redis,
    ):
        yield redis


class TestRateLimit:
    """Testes do sliding window rate limiter."""

    async def test_allows_within_limit(self):
        """Permite requisições dentro do limite."""
        # Limite padrão: 30/hora
        for _ in range(5):
            await check_rate_limit("+5511999999999")
        # Sem exceção = dentro do limite

    async def test_blocks_over_limit(self, monkeypatch):
        """Bloqueia quando excede o limite."""
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "rate_limit_per_hour", 3)

        # Primeiras 3 passam
        for _ in range(3):
            await check_rate_limit("+5511999999999")

        # A 4ª deve ser bloqueada
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit("+5511999999999")
        assert exc_info.value.status_code == 429

    async def test_different_phones_independent(self, monkeypatch):
        """Rate limit é independente por telefone."""
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "rate_limit_per_hour", 2)

        # Telefone A: 2 requisições (no limite)
        await check_rate_limit("+5511111111111")
        await check_rate_limit("+5511111111111")

        # Telefone B: ainda pode
        await check_rate_limit("+5522222222222")

    async def test_old_requests_expire(self, monkeypatch, fake_redis):
        """Requisições antigas (>1h) não contam no limite."""
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "rate_limit_per_hour", 2)

        # Simula requisições de 2 horas atrás direto no sorted set
        old_time = time.time() - 7200
        await fake_redis.zadd(
            "ratelimit:+5511999999999", {"old-1": old_time, "old-2": old_time}
        )

        # Deve permitir novas requisições (as antigas expiraram)
        await check_rate_limit("+5511999999999")
