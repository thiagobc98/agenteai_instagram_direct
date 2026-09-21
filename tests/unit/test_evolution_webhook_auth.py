"""Testes da validação do token secreto do webhook Evolution.

O Evolution API não assina os webhooks (sem equivalente ao
X-Twilio-Signature do Twilio) — a proteção é um token compartilhado
próprio, validado a partir do path `/webhook/evolution/{token}`.
"""

from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from whatsapp_langchain.server.dependencies import validate_evolution_webhook_token
from whatsapp_langchain.server.main import app

client = TestClient(app, raise_server_exceptions=False)

VALID_TOKEN = "test-webhook-token-abc123"

MESSAGE_PAYLOAD = {
    "event": "messages.upsert",
    "data": {
        "key": {
            "remoteJid": "5511999999999@s.whatsapp.net",
            "fromMe": False,
            "id": "MSG123",
        },
        "message": {"conversation": "Olá"},
        "messageType": "conversation",
    },
}


@pytest.fixture(autouse=True)
def mock_db():
    """Mock do banco de dados e do Redis para testes sem infra real."""
    mock_pool = AsyncMock()
    fake_redis = fakeredis.FakeAsyncRedis()

    with (
        patch(
            "whatsapp_langchain.server.routes.health.check_db_health",
            return_value=True,
        ),
        patch(
            "whatsapp_langchain.server.routes.webhook_evolution.get_pool",
            return_value=mock_pool,
        ),
        patch("whatsapp_langchain.shared.db.get_pool", return_value=mock_pool),
        patch("whatsapp_langchain.shared.db.run_migrations"),
        patch("whatsapp_langchain.shared.db.close_pool"),
        patch(
            "whatsapp_langchain.server.dependencies.get_redis",
            return_value=fake_redis,
        ),
    ):
        yield mock_pool


class TestValidateEvolutionWebhookTokenUnit:
    """Testes diretos da dependency (sem HTTP)."""

    async def test_raises_500_when_not_configured(self, monkeypatch):
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "evolution_webhook_token", "")

        with pytest.raises(HTTPException) as exc_info:
            await validate_evolution_webhook_token("qualquer-token")
        assert exc_info.value.status_code == 500

    async def test_raises_403_on_wrong_token(self, monkeypatch):
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "evolution_webhook_token", VALID_TOKEN)

        with pytest.raises(HTTPException) as exc_info:
            await validate_evolution_webhook_token("token-errado")
        assert exc_info.value.status_code == 403

    async def test_accepts_matching_token(self, monkeypatch):
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "evolution_webhook_token", VALID_TOKEN)

        # Não deve levantar exceção
        await validate_evolution_webhook_token(VALID_TOKEN)


class TestWebhookRouteTokenValidation:
    """Testes de round-trip via TestClient contra a rota real."""

    @patch("whatsapp_langchain.server.routes.webhook_evolution.enqueue_or_buffer")
    def test_accepts_valid_token(self, mock_enqueue, monkeypatch):
        from whatsapp_langchain.shared.config import settings
        from whatsapp_langchain.shared.models import EnqueueResult

        monkeypatch.setattr(settings, "evolution_webhook_token", VALID_TOKEN)
        mock_enqueue.return_value = EnqueueResult(message_id=1, is_buffered=False)

        response = client.post(
            f"/webhook/evolution/{VALID_TOKEN}?agent=secretaria",
            json=MESSAGE_PAYLOAD,
        )
        assert response.status_code == 200

    def test_rejects_wrong_token(self, monkeypatch):
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "evolution_webhook_token", VALID_TOKEN)

        response = client.post(
            "/webhook/evolution/token-errado?agent=secretaria",
            json=MESSAGE_PAYLOAD,
        )
        assert response.status_code == 403

    def test_returns_500_when_token_not_configured(self, monkeypatch):
        from whatsapp_langchain.shared.config import settings

        monkeypatch.setattr(settings, "evolution_webhook_token", "")

        response = client.post(
            f"/webhook/evolution/{VALID_TOKEN}?agent=secretaria",
            json=MESSAGE_PAYLOAD,
        )
        assert response.status_code == 500
