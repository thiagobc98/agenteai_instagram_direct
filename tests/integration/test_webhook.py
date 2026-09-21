"""Testes de integração do webhook — FastAPI TestClient.

Testa o fluxo de webhook sem banco de dados real.
Usa mocking para simular pool e operações de fila.
"""

import hashlib
import hmac
import json
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

    monkeypatch.setattr(settings, "instagram_app_secret", SecretStr(APP_SECRET))
    monkeypatch.setattr(settings, "instagram_verify_token", SecretStr(VERIFY_TOKEN))
    monkeypatch.setattr(settings, "instagram_business_account_id", "")

    mock_pool = AsyncMock()
    fake_redis = fakeredis.FakeAsyncRedis()

    with (
        patch(
            "whatsapp_langchain.server.routes.health.check_db_health",
            return_value=True,
        ),
        patch(
            "whatsapp_langchain.server.routes.webhook_instagram.get_pool",
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


APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
SENDER = "17841400000000001"
BUSINESS = "17841400000000000"
ROUTE = "whatsapp_langchain.server.routes.webhook_instagram"


def _message_payload(text: str = "Olá", sender: str = SENDER) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": BUSINESS,
                "time": 1700000000000,
                "messaging": [
                    {
                        "sender": {"id": sender},
                        "recipient": {"id": BUSINESS},
                        "timestamp": 1700000000000,
                        "message": {"mid": "MID123", "text": text},
                    }
                ],
            }
        ],
    }


def _post(payload: dict, path: str = "/webhook/instagram?agent=secretaria"):
    """POST assinado como a Meta faz (HMAC-SHA256 do body com o App Secret)."""
    raw = json.dumps(payload).encode()
    signature = hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        path,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={signature}",
        },
    )


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
            json={"external_id": SENDER, "message": "Olá"},
        )
        # Sem agent= -> 422 (query param obrigatório)
        assert response.status_code == 422

    def test_sync_nonexistent_agent(self):
        """Deve retornar erro para agente inexistente."""
        response = client.post(
            "/webhook/sync?agent=nao_existe",
            json={"external_id": SENDER, "message": "Olá"},
        )
        assert response.status_code == 400


class TestWebhookInstagram:
    """Testes do webhook do Instagram."""

    def test_verification_handshake(self):
        """GET de verificação devolve o hub.challenge em texto puro."""
        response = client.get(
            "/webhook/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "987654",
            },
        )
        assert response.status_code == 200
        assert response.text == "987654"

    def test_verification_rejects_wrong_token(self):
        response = client.get(
            "/webhook/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "errado",
                "hub.challenge": "987654",
            },
        )
        assert response.status_code == 403

    def test_requires_agent(self):
        """Deve exigir o query param 'agent'."""
        response = _post(_message_payload(), path="/webhook/instagram")
        # Sem agent= -> 422
        assert response.status_code == 422

    def test_nonexistent_agent(self):
        """Deve retornar erro para agente inexistente."""
        response = _post(_message_payload(), path="/webhook/instagram?agent=nao_existe")
        assert response.status_code == 400

    def test_rejects_invalid_signature(self):
        """Deve rejeitar com 403 quando a assinatura não confere."""
        response = client.post(
            "/webhook/instagram?agent=secretaria",
            json=_message_payload(),
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )
        assert response.status_code == 403

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_enqueues_message(self, mock_enqueue):
        """Deve enfileirar mensagem e confirmar recebimento."""
        from whatsapp_langchain.shared.models import EnqueueResult

        mock_enqueue.return_value = EnqueueResult(message_id=1, is_buffered=False)

        response = _post(_message_payload())
        assert response.status_code == 200
        assert response.json() == {"received": True, "enqueued": 1}
        mock_enqueue.assert_awaited_once()
        assert mock_enqueue.call_args.kwargs["external_id"] == SENDER

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_ignores_own_echoed_messages(self, mock_enqueue):
        """Mensagens com is_echo=true (eco da própria conta) são ignoradas."""
        payload = _message_payload()
        payload["entry"][0]["messaging"][0]["message"]["is_echo"] = True

        response = _post(payload)
        assert response.status_code == 200
        assert response.json() == {"ignored": True}
        mock_enqueue.assert_not_awaited()

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_ignores_non_message_events(self, mock_enqueue):
        """Eventos que não são mensagem (ex: leitura) são ignorados."""
        payload = _message_payload()
        event = payload["entry"][0]["messaging"][0]
        del event["message"]
        event["read"] = {"mid": "MID123"}

        response = _post(payload)
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
