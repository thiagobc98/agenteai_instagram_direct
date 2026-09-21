"""Testes de integração do webhook — FastAPI TestClient.

Testa o fluxo de webhook sem banco de dados real.
Usa mocking para simular pool e operações de fila.
"""

from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whatsapp_langchain import __version__
from whatsapp_langchain.server.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    """Mock do banco de dados e do Redis para testes sem infra real."""
    from whatsapp_langchain.shared.config import settings

    monkeypatch.setattr(settings, "evolution_webhook_token", "test-webhook-token")

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
        patch(
            "whatsapp_langchain.server.routes.admin.get_pool",
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


WEBHOOK_TOKEN = "test-webhook-token"


def _message_payload(text: str = "Olá", phone: str = "5511999999999") -> dict:
    return {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": f"{phone}@s.whatsapp.net",
                "fromMe": False,
                "id": "MSG123",
            },
            "message": {"conversation": text},
            "messageType": "conversation",
        },
    }


@pytest.fixture
def admin_session(monkeypatch):
    """Configura credenciais de admin e retorna um client autenticado (isolado)."""
    from whatsapp_langchain.shared.config import settings

    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", SecretStr("test-password"))

    authed_client = TestClient(app, raise_server_exceptions=False)
    login_response = authed_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-password"},
    )
    assert login_response.status_code == 200
    return authed_client


class TestHealthCheck:
    """Testes do endpoint /health."""

    def test_health_ok(self):
        """Retorna 200 quando o banco está acessível."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "database": "connected",
            "version": __version__,
        }


class TestWebhookSync:
    """Testes do webhook síncrono."""

    def test_sync_requires_agent(self):
        """Deve exigir o query param 'agent'."""
        response = client.post(
            "/webhook/sync",
            json={"phone": "+5511999999999", "message": "Olá"},
        )
        # Sem agent= -> 422 (query param obrigatório)
        assert response.status_code == 422

    def test_sync_nonexistent_agent(self):
        """Deve retornar erro para agente inexistente."""
        response = client.post(
            "/webhook/sync?agent=nao_existe",
            json={"phone": "+5511999999999", "message": "Olá"},
        )
        assert response.status_code == 400


class TestWebhookEvolution:
    """Testes do webhook Evolution API."""

    def test_requires_agent(self):
        """Deve exigir o query param 'agent'."""
        response = client.post(
            f"/webhook/evolution/{WEBHOOK_TOKEN}",
            json=_message_payload(),
        )
        # Sem agent= -> 422
        assert response.status_code == 422

    def test_nonexistent_agent(self):
        """Deve retornar erro para agente inexistente."""
        response = client.post(
            f"/webhook/evolution/{WEBHOOK_TOKEN}?agent=nao_existe",
            json=_message_payload(),
        )
        assert response.status_code == 400

    def test_rejects_wrong_token(self):
        """Deve rejeitar com 403 quando o token do path não confere."""
        response = client.post(
            "/webhook/evolution/token-errado?agent=secretaria",
            json=_message_payload(),
        )
        assert response.status_code == 403

    @patch("whatsapp_langchain.server.routes.webhook_evolution.enqueue_or_buffer")
    def test_enqueues_message(self, mock_enqueue):
        """Deve enfileirar mensagem e confirmar recebimento."""
        from whatsapp_langchain.shared.models import EnqueueResult

        mock_enqueue.return_value = EnqueueResult(message_id=1, is_buffered=False)

        response = client.post(
            f"/webhook/evolution/{WEBHOOK_TOKEN}?agent=secretaria",
            json=_message_payload(),
        )
        assert response.status_code == 200
        assert response.json() == {"received": True}
        mock_enqueue.assert_awaited_once()
        assert mock_enqueue.call_args.kwargs["phone_number"] == "+5511999999999"

    @patch("whatsapp_langchain.server.routes.webhook_evolution.enqueue_or_buffer")
    def test_ignores_group_messages(self, mock_enqueue):
        """Mensagens de grupo (@g.us) devem ser ignoradas sem enfileirar."""
        payload = _message_payload()
        payload["data"]["key"]["remoteJid"] = "120363000000000000@g.us"

        response = client.post(
            f"/webhook/evolution/{WEBHOOK_TOKEN}?agent=secretaria",
            json=payload,
        )
        assert response.status_code == 200
        assert response.json() == {"ignored": True}
        mock_enqueue.assert_not_awaited()

    @patch("whatsapp_langchain.server.routes.webhook_evolution.enqueue_or_buffer")
    def test_ignores_own_echoed_messages(self, mock_enqueue):
        """Mensagens com fromMe=true (eco do próprio bot) são ignoradas."""
        payload = _message_payload()
        payload["data"]["key"]["fromMe"] = True

        response = client.post(
            f"/webhook/evolution/{WEBHOOK_TOKEN}?agent=secretaria",
            json=payload,
        )
        assert response.status_code == 200
        assert response.json() == {"ignored": True}
        mock_enqueue.assert_not_awaited()

    @patch("whatsapp_langchain.server.routes.webhook_evolution.enqueue_or_buffer")
    def test_ignores_non_message_events(self, mock_enqueue):
        """Eventos que não são messages.upsert são ignorados."""
        response = client.post(
            f"/webhook/evolution/{WEBHOOK_TOKEN}?agent=secretaria",
            json={"event": "connection.update", "data": {}},
        )
        assert response.status_code == 200
        assert response.json() == {"ignored": True}
        mock_enqueue.assert_not_awaited()


class TestAdminRoutes:
    """Testes das rotas administrativas."""

    def test_list_agents_requires_auth(self):
        """Sem sessão de admin, deve retornar 401."""
        response = TestClient(app, raise_server_exceptions=False).get("/api/agents")
        assert response.status_code == 401

    def test_list_agents(self, admin_session):
        """Deve listar agentes disponíveis quando autenticado."""
        response = admin_session.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "secretaria" in data["agents"]
