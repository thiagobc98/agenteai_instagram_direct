"""Testes de integração da autenticação do admin panel.

Cobre login/logout/me e a proteção das rotas administrativas via sessão.
Usa mocking para simular pool e Redis, seguindo o padrão de
tests/integration/test_webhook.py.
"""

from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whatsapp_langchain.server.main import app
from whatsapp_langchain.shared.config import settings


@pytest.fixture(autouse=True)
def mock_db():
    """Mock do banco de dados e do Redis para testes sem infra real."""
    mock_pool = AsyncMock()
    fake_redis = fakeredis.FakeAsyncRedis()

    with (
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


@pytest.fixture(autouse=True)
def admin_credentials(monkeypatch):
    """Configura usuário/senha de admin para os testes de auth."""
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", SecretStr("correct-password"))


@pytest.fixture
def client():
    """Client isolado por teste (evita cookies vazando entre testes)."""
    return TestClient(app, raise_server_exceptions=False)


ADMIN_ROUTES = ["/api/agents", "/api/chats", "/api/metrics"]


class TestLogin:
    """Testes do fluxo de login."""

    def test_login_success(self, client):
        """Credenciais corretas retornam 200 e setam o cookie de sessão."""
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        assert response.status_code == 200
        assert response.json() == {"username": "admin"}
        assert "session" in response.cookies

    def test_login_wrong_password(self, client):
        """Senha incorreta retorna 401."""
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 401

    def test_login_wrong_username(self, client):
        """Usuário incorreto retorna 401."""
        response = client.post(
            "/api/auth/login",
            json={"username": "not-admin", "password": "correct-password"},
        )
        assert response.status_code == 401

    def test_login_no_password_configured(self, client, monkeypatch):
        """Sem ADMIN_PASSWORD configurada, login deve falhar sempre."""
        monkeypatch.setattr(settings, "admin_password", None)
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": ""},
        )
        assert response.status_code == 401


class TestMe:
    """Testes do endpoint /api/auth/me."""

    def test_me_without_session(self, client):
        """Sem sessão, retorna 401."""
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_me_with_session(self, client):
        """Com sessão válida, retorna o usuário autenticado."""
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        response = client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json() == {"username": "admin"}


class TestLogout:
    """Testes do endpoint /api/auth/logout."""

    def test_logout_clears_session(self, client):
        """Após logout, /me volta a retornar 401."""
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        logout_response = client.post("/api/auth/logout")
        assert logout_response.status_code == 200

        me_response = client.get("/api/auth/me")
        assert me_response.status_code == 401


class TestAdminRouteProtection:
    """Todas as rotas /api/* administrativas exigem sessão de admin."""

    @pytest.mark.parametrize("path", ADMIN_ROUTES)
    def test_route_requires_auth(self, client, path):
        """Sem cookie de sessão, retorna 401."""
        response = client.get(path)
        assert response.status_code == 401

    def test_route_allows_authenticated_admin(self, client):
        """Com sessão válida, a rota responde normalmente (200).

        Usa apenas /api/agents (não toca o banco) — /api/chats e
        /api/metrics fazem query real via pool.connection(), fora do
        escopo do mock_pool genérico usado aqui.
        """
        login_response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        assert login_response.status_code == 200

        response = client.get("/api/agents")
        assert response.status_code == 200
