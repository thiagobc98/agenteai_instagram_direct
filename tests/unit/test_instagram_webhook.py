"""Testes do webhook do Instagram: handshake, assinatura HMAC e enfileiramento.

A Meta verifica o webhook com um GET (hub.mode/hub.verify_token/hub.challenge)
e assina cada POST com o App Secret (header X-Hub-Signature-256).
"""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whatsapp_langchain.server.dependencies import verify_instagram_signature
from whatsapp_langchain.server.main import app
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.models import EnqueueResult

client = TestClient(app, raise_server_exceptions=False)

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
SENDER = "17841400000000001"
BUSINESS = "17841400000000000"
ROUTE = "whatsapp_langchain.server.routes.webhook_instagram"


def _payload(*messages: dict) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": BUSINESS,
                "time": 1700000000000,
                "messaging": [
                    {
                        "sender": {"id": SENDER},
                        "recipient": {"id": BUSINESS},
                        "timestamp": 1700000000000,
                        "message": message,
                    }
                    for message in messages
                ],
            }
        ],
    }


TEXT_PAYLOAD = _payload({"mid": "MID1", "text": "Olá"})


def sign(raw: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def post_signed(payload: dict, *, agent: str = "secretaria", secret: str = APP_SECRET):
    raw = json.dumps(payload).encode()
    return client.post(
        f"/webhook/instagram?agent={agent}",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(raw, secret),
        },
    )


@pytest.fixture(autouse=True)
def mock_infra(monkeypatch):
    """Mock do banco e do Redis para testes sem infra real."""
    mock_pool = AsyncMock()
    fake_redis = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(settings, "instagram_app_secret", SecretStr(APP_SECRET))
    monkeypatch.setattr(settings, "instagram_verify_token", SecretStr(VERIFY_TOKEN))
    monkeypatch.setattr(settings, "instagram_business_account_id", "")

    with (
        patch(
            "whatsapp_langchain.server.routes.health.check_db_health",
            return_value=True,
        ),
        patch(f"{ROUTE}.get_pool", return_value=mock_pool),
        patch("whatsapp_langchain.shared.db.get_pool", return_value=mock_pool),
        patch("whatsapp_langchain.shared.db.run_migrations"),
        patch("whatsapp_langchain.shared.db.close_pool"),
        patch(
            "whatsapp_langchain.server.dependencies.get_redis",
            return_value=fake_redis,
        ),
    ):
        yield mock_pool


class TestVerifySignature:
    """Testes diretos da função de verificação (sem HTTP)."""

    def test_accepts_valid_signature(self):
        raw = b'{"a": 1}'
        assert verify_instagram_signature(raw, sign(raw), APP_SECRET)

    def test_rejects_wrong_secret(self):
        raw = b'{"a": 1}'
        assert not verify_instagram_signature(raw, sign(raw, "outro"), APP_SECRET)

    def test_rejects_tampered_body(self):
        raw = b'{"a": 1}'
        assert not verify_instagram_signature(b'{"a": 2}', sign(raw), APP_SECRET)

    def test_rejects_missing_header(self):
        assert not verify_instagram_signature(b"{}", None, APP_SECRET)

    def test_rejects_header_without_sha256_prefix(self):
        raw = b"{}"
        bare = sign(raw).removeprefix("sha256=")
        assert not verify_instagram_signature(raw, bare, APP_SECRET)


class TestVerificationHandshake:
    def _get(self, **params):
        return client.get("/webhook/instagram", params=params)

    def test_returns_challenge_in_plain_text_when_token_matches(self):
        response = self._get(
            **{
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "1158201444",
            }
        )
        assert response.status_code == 200
        assert response.text == "1158201444"
        assert response.headers["content-type"].startswith("text/plain")

    def test_rejects_wrong_token(self):
        response = self._get(
            **{
                "hub.mode": "subscribe",
                "hub.verify_token": "errado",
                "hub.challenge": "1",
            }
        )
        assert response.status_code == 403

    def test_rejects_missing_token(self):
        response = self._get(**{"hub.mode": "subscribe", "hub.challenge": "1"})
        assert response.status_code == 403

    def test_rejects_wrong_mode(self):
        response = self._get(
            **{
                "hub.mode": "unsubscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "1",
            }
        )
        assert response.status_code == 403

    def test_rejects_missing_challenge(self):
        response = self._get(
            **{"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN}
        )
        assert response.status_code == 403

    def test_returns_500_when_verify_token_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "instagram_verify_token", None)
        response = self._get(
            **{
                "hub.mode": "subscribe",
                "hub.verify_token": "",
                "hub.challenge": "1",
            }
        )
        assert response.status_code == 500


class TestSignatureValidationOnPost:
    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_accepts_valid_signature(self, mock_enqueue):
        mock_enqueue.return_value = EnqueueResult(message_id=1, is_buffered=False)
        response = post_signed(TEXT_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == {"received": True, "enqueued": 1}

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_rejects_wrong_signature(self, mock_enqueue):
        response = post_signed(TEXT_PAYLOAD, secret="segredo-errado")
        assert response.status_code == 403
        mock_enqueue.assert_not_called()

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_rejects_missing_signature(self, mock_enqueue):
        response = client.post("/webhook/instagram?agent=secretaria", json=TEXT_PAYLOAD)
        assert response.status_code == 403
        mock_enqueue.assert_not_called()

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_rejects_body_modified_after_signing(self, mock_enqueue):
        raw = json.dumps(TEXT_PAYLOAD).encode()
        response = client.post(
            "/webhook/instagram?agent=secretaria",
            content=raw + b" ",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sign(raw),
            },
        )
        assert response.status_code == 403
        mock_enqueue.assert_not_called()

    def test_returns_500_when_app_secret_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "instagram_app_secret", None)
        response = post_signed(TEXT_PAYLOAD)
        assert response.status_code == 500


class TestPostFlow:
    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_enqueues_text_message(self, mock_enqueue):
        mock_enqueue.return_value = EnqueueResult(message_id=7, is_buffered=False)
        post_signed(TEXT_PAYLOAD)

        kwargs = mock_enqueue.call_args.kwargs
        assert kwargs["external_id"] == SENDER
        assert kwargs["agent_id"] == "secretaria"
        assert kwargs["body"] == "Olá"
        assert kwargs["message_id"] == "MID1"
        assert kwargs["media_url"] is None
        assert kwargs["media_type"] is None

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_enqueues_media_url(self, mock_enqueue):
        mock_enqueue.return_value = EnqueueResult(message_id=8, is_buffered=False)
        payload = _payload(
            {
                "mid": "MID2",
                "attachments": [
                    {"type": "image", "payload": {"url": "https://cdn.example/i.jpg"}}
                ],
            }
        )
        post_signed(payload)

        kwargs = mock_enqueue.call_args.kwargs
        assert kwargs["media_url"] == "https://cdn.example/i.jpg"
        assert kwargs["media_type"] == "image/*"

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_ignores_echo_events(self, mock_enqueue):
        payload = _payload({"mid": "M", "text": "resposta do bot", "is_echo": True})
        response = post_signed(payload)
        assert response.status_code == 200
        assert response.json() == {"ignored": True}
        mock_enqueue.assert_not_called()

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_ignores_events_from_own_account(self, mock_enqueue, monkeypatch):
        monkeypatch.setattr(settings, "instagram_business_account_id", SENDER)
        post_signed(TEXT_PAYLOAD)
        mock_enqueue.assert_not_called()

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_enqueues_each_message_of_a_batch(self, mock_enqueue):
        mock_enqueue.return_value = EnqueueResult(message_id=1, is_buffered=False)
        payload = _payload({"mid": "A", "text": "um"}, {"mid": "B", "text": "dois"})
        response = post_signed(payload)
        assert response.json() == {"received": True, "enqueued": 2}
        assert mock_enqueue.call_count == 2

    @patch(f"{ROUTE}.enqueue_or_buffer")
    def test_rate_limit_drops_only_the_excess_message(self, mock_enqueue, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_per_hour", 1)
        mock_enqueue.return_value = EnqueueResult(message_id=1, is_buffered=False)
        payload = _payload({"mid": "A", "text": "um"}, {"mid": "B", "text": "dois"})

        response = post_signed(payload)

        assert response.status_code == 200
        assert response.json() == {"received": True, "enqueued": 1}
        assert mock_enqueue.call_count == 1

    def test_rejects_unknown_agent(self):
        response = post_signed(TEXT_PAYLOAD, agent="nao_existe")
        assert response.status_code == 400

    def test_rejects_invalid_json_with_valid_signature(self):
        raw = b"not-json"
        response = client.post(
            "/webhook/instagram?agent=secretaria",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sign(raw),
            },
        )
        assert response.status_code == 400

    def test_requires_agent_query_param(self):
        raw = json.dumps(TEXT_PAYLOAD).encode()
        response = client.post(
            "/webhook/instagram",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sign(raw),
            },
        )
        assert response.status_code == 422
