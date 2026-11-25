"""Avisos no WhatsApp do atendente (Wuzapi): formatação, envio e rotas."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whatsapp_langchain.server.main import app
from whatsapp_langchain.shared import attendant_notify as notify
from whatsapp_langchain.shared.attendant_notify import (
    NotifySettings,
    PendingNotification,
    format_notification,
    message_preview,
    normalize_recipients,
)
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.wuzapi_client import (
    WuzapiClient,
    WuzapiError,
    br_number_variants,
)
from whatsapp_langchain.worker import notifier

NOW = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
ATTENDANT = "5531983181760"


def item(i: int = 1, body: str = "Quanto custa?", media: str | None = None):
    return PendingNotification(
        id=i,
        external_id="IG1",
        body=body,
        media_type=media,
        attempts=0,
        created_at=NOW + timedelta(seconds=i),
    )


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------


class TestPhones:
    def test_variants_with_and_without_the_extra_9(self):
        assert br_number_variants("(31) 98318-1760") == [
            "5531983181760",
            "553183181760",
        ]
        assert br_number_variants("553183181760") == ["553183181760", "5531983181760"]

    def test_normalize_recipients(self):
        valid, invalid = normalize_recipients(
            ["31 98318-1760", "+55 31 98318-1760", "", "123"]
        )
        assert valid == [ATTENDANT]
        assert invalid == ["123"]


class TestPreview:
    @pytest.mark.parametrize(
        ("media", "label"),
        [
            ("image/*", "📷 foto"),
            ("audio/*", "🎤 áudio"),
            ("unsupported/ig_reel", "🎬 reels compartilhado"),
            ("unsupported/algo_novo", "📎 algo_novo"),
        ],
    )
    def test_media_labels(self, media, label):
        assert message_preview("", media) == label

    def test_text_with_media(self):
        assert message_preview("olha esse", "image/*") == "📷 foto: olha esse"

    def test_long_text_is_clipped(self):
        assert len(message_preview("a " * 500, None)) <= notify.PREVIEW_CHARS

    def test_empty(self):
        assert message_preview("", None) == "(mensagem sem texto)"


class TestFormat:
    def test_single_message(self):
        text = format_notification(
            [item()], username="_thibec", name="Thiago", panel_url=None
        )
        assert text.startswith("📩 *Nova mensagem no Direct*")
        assert "*@_thibec (Thiago)*" in text
        assert "Quanto custa?" in text
        assert "https://ig.me/m/_thibec" in text
        assert "painel" not in text

    def test_burst_is_grouped(self):
        items = [item(i, f"msg {i}") for i in range(1, 4)]
        text = format_notification(items, username="x", name=None, panel_url=None)
        assert "_3 mensagens:_" in text
        assert text.index("msg 1") < text.index("msg 3")

    def test_many_messages_are_capped(self):
        items = [item(i, f"msg {i}") for i in range(1, 13)]
        text = format_notification(items, username="x", name=None, panel_url=None)
        assert "… e mais 4" in text

    def test_without_username_has_no_instagram_link(self):
        text = format_notification(
            [item()], username=None, name=None, panel_url="https://p/chats/IG1"
        )
        assert "Cliente sem @" in text
        assert "ig.me" not in text
        assert "Ver no painel: https://p/chats/IG1" in text

    def test_retry_backoff_grows(self):
        assert [notify.retry_delay_seconds(n) for n in (1, 2, 3)] == [30, 60, 120]


def test_panel_link_only_when_public(monkeypatch):
    monkeypatch.setattr(settings, "frontend_origin", "http://localhost:3000")
    assert notifier.panel_chat_url("IG1") is None
    monkeypatch.setattr(settings, "frontend_origin", "https://painel.loja.com/")
    assert notifier.panel_chat_url("IG1") == "https://painel.loja.com/chats/IG1"


# ---------------------------------------------------------------------------
# Cliente Wuzapi (HTTP simulado)
# ---------------------------------------------------------------------------


@pytest.fixture
def http(monkeypatch):
    state: dict = {"requests": [], "status": 200, "body": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return httpx.Response(state["status"], json=state["body"])

    original = httpx.AsyncClient.__init__

    def patched(self_client, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self_client, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return state


class TestWuzapiClient:
    async def test_send_text(self, http):
        http["body"] = {"code": 200, "data": {"Id": "ABC"}, "success": True}
        msg_id = await WuzapiClient("http://w:8080", "tok").send_text(
            "553183181760@s.whatsapp.net", "oi"
        )
        req = http["requests"][0]
        assert str(req.url) == "http://w:8080/chat/send/text"
        assert req.headers["token"] == "tok"
        assert json.loads(req.content) == {"Phone": "553183181760", "Body": "oi"}
        assert msg_id == "ABC"

    async def test_finds_the_registered_variant(self, http):
        http["body"] = {
            "data": {
                "Users": [
                    {"Query": "5531983181760", "IsInWhatsapp": False, "JID": ""},
                    {
                        "Query": "553183181760",
                        "IsInWhatsapp": True,
                        "JID": "553183181760@s.whatsapp.net",
                    },
                ]
            }
        }
        jid = await WuzapiClient("http://w", "t").whatsapp_jid("31983181760")
        assert jid == "553183181760@s.whatsapp.net"
        sent = json.loads(http["requests"][0].content)
        assert sent == {"Phone": ["5531983181760", "553183181760"]}

    async def test_number_without_whatsapp(self, http):
        http["body"] = {"data": {"Users": [{"Query": "5531983181760"}]}}
        assert await WuzapiClient("http://w", "t").whatsapp_jid(ATTENDANT) is None

    async def test_session_status(self, http):
        http["body"] = {
            "data": {"Connected": True, "LoggedIn": True, "Jid": "5531999:12@s"}
        }
        status = await WuzapiClient("http://w", "t").session_status()
        assert status == {"connected": True, "logged_in": True, "jid": "5531999:12@s"}

    async def test_error_status_raises(self, http):
        http["status"], http["body"] = 401, {"error": "unauthorized"}
        with pytest.raises(WuzapiError) as exc:
            await WuzapiClient("http://w", "t").session_status()
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Worker: envio dos avisos
# ---------------------------------------------------------------------------


@pytest.fixture
def worker_env():
    store = AsyncMock()
    store.claim_batch.return_value = [item(1), item(2, "tem no 36?")]
    store.get_settings.return_value = NotifySettings(True, [ATTENDANT], None, None)
    store.mark_failed.return_value = False
    store.format_notification = format_notification
    wuzapi = AsyncMock()
    wuzapi.whatsapp_jid.return_value = "553183181760@s.whatsapp.net"
    notifier._jid_cache.clear()
    with (
        patch.object(notifier, "store", store),
        patch.object(notifier, "_contact", new=AsyncMock(return_value=("ana", None))),
    ):
        yield store, wuzapi


class TestNotifier:
    async def test_nothing_to_do(self, worker_env):
        store, wuzapi = worker_env
        store.claim_batch.return_value = []
        assert await notifier.notify_next(object(), wuzapi) is False
        wuzapi.send_text.assert_not_awaited()

    async def test_sends_one_grouped_message(self, worker_env):
        store, wuzapi = worker_env
        assert await notifier.notify_next(object(), wuzapi) is True
        wuzapi.send_text.assert_awaited_once()
        jid, text = wuzapi.send_text.await_args.args
        assert jid == "553183181760@s.whatsapp.net"
        assert "_2 mensagens:_" in text and "tem no 36?" in text
        store.mark_sent.assert_awaited_once_with(
            store.mark_sent.await_args.args[0], [1, 2], None
        )

    async def test_jid_is_cached(self, worker_env):
        _, wuzapi = worker_env
        await notifier.notify_next(object(), wuzapi)
        await notifier.notify_next(object(), wuzapi)
        assert wuzapi.whatsapp_jid.await_count == 1

    async def test_disabled_skips(self, worker_env):
        store, wuzapi = worker_env
        store.get_settings.return_value = NotifySettings(False, [ATTENDANT], None, None)
        await notifier.notify_next(object(), wuzapi)
        store.mark_skipped.assert_awaited_once()
        wuzapi.send_text.assert_not_awaited()

    async def test_no_recipients_skips(self, worker_env):
        store, wuzapi = worker_env
        store.get_settings.return_value = NotifySettings(True, [], None, None)
        await notifier.notify_next(object(), wuzapi)
        assert "nenhum celular" in store.mark_skipped.await_args.args[2]

    async def test_without_wuzapi_skips(self, worker_env):
        store, _ = worker_env
        await notifier.notify_next(object(), None)
        assert "Wuzapi" in store.mark_skipped.await_args.args[2]

    async def test_failure_schedules_retry(self, worker_env):
        store, wuzapi = worker_env
        wuzapi.send_text.side_effect = WuzapiError(500, "not logged in")
        await notifier.notify_next(object(), wuzapi)
        store.mark_failed.assert_awaited_once()
        assert "not logged in" in store.mark_failed.await_args.args[2]
        store.mark_sent.assert_not_awaited()

    async def test_partial_failure_is_not_resent(self, worker_env):
        store, wuzapi = worker_env
        store.get_settings.return_value = NotifySettings(
            True, [ATTENDANT, "5531999998888"], None, None
        )
        wuzapi.send_text.side_effect = [None, WuzapiError(500, "x")]
        await notifier.notify_next(object(), wuzapi)
        store.mark_sent.assert_awaited_once()
        store.mark_failed.assert_not_awaited()

    async def test_number_without_whatsapp_fails(self, worker_env):
        store, wuzapi = worker_env
        wuzapi.whatsapp_jid.return_value = None
        await notifier.notify_next(object(), wuzapi)
        assert "não tem WhatsApp" in store.mark_failed.await_args.args[2]


# ---------------------------------------------------------------------------
# Webhook: um aviso por mensagem, sem atrapalhar o atendimento
# ---------------------------------------------------------------------------

APP_SECRET = "app-secret"
WEBHOOK_ROUTE = "whatsapp_langchain.server.routes.webhook_instagram"
client = TestClient(app, raise_server_exceptions=False)


def dm_payload() -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": "BIZ",
                "time": 1,
                "messaging": [
                    {
                        "sender": {"id": "IG1"},
                        "recipient": {"id": "BIZ"},
                        "timestamp": 1,
                        "message": {"mid": "MID1", "text": "Quanto custa?"},
                    }
                ],
            }
        ],
    }


def post_signed(payload: dict):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhook/instagram?agent=secretaria",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )


@pytest.fixture
def webhook_env(monkeypatch):
    monkeypatch.setattr(settings, "instagram_app_secret", SecretStr(APP_SECRET))
    monkeypatch.setattr(settings, "instagram_business_account_id", "BIZ")
    with (
        patch(f"{WEBHOOK_ROUTE}.get_pool", new=AsyncMock(return_value=object())),
        patch(f"{WEBHOOK_ROUTE}.check_rate_limit", new=AsyncMock()),
        patch(f"{WEBHOOK_ROUTE}.enqueue_or_buffer", new=AsyncMock()) as enqueue,
        patch(f"{WEBHOOK_ROUTE}.enqueue_notification", new=AsyncMock()) as notify_mock,
    ):
        yield enqueue, notify_mock


class TestWebhookNotification:
    def test_each_message_creates_a_notification(self, webhook_env):
        enqueue, notify_mock = webhook_env
        assert post_signed(dm_payload()).status_code == 200
        enqueue.assert_awaited_once()
        kwargs = notify_mock.await_args.kwargs
        assert kwargs["external_id"] == "IG1"
        assert kwargs["body"] == "Quanto custa?"
        assert kwargs["source_message_id"] == "MID1"

    def test_notification_failure_does_not_break_the_webhook(self, webhook_env):
        enqueue, notify_mock = webhook_env
        notify_mock.side_effect = RuntimeError("db down")
        response = post_signed(dm_payload())
        assert response.status_code == 200
        assert response.json()["enqueued"] == 1


# ---------------------------------------------------------------------------
# Rotas do painel
# ---------------------------------------------------------------------------

ROUTE = "whatsapp_langchain.server.routes.whatsapp_notify"


@pytest.fixture
def panel_env():
    from whatsapp_langchain.server.dependencies import require_admin_session

    app.dependency_overrides[require_admin_session] = lambda: "admin"
    store = AsyncMock()
    store.normalize_recipients = normalize_recipients
    store.save_settings.side_effect = lambda pool, **kw: NotifySettings(
        kw["enabled"], kw["recipients"], kw["updated_by"], None
    )
    with (
        patch(f"{ROUTE}.get_pool", new=AsyncMock(return_value=object())),
        patch(f"{ROUTE}.store", store),
    ):
        yield store
    app.dependency_overrides.clear()


class TestPanelRoutes:
    def test_saves_normalized_numbers(self, panel_env):
        resp = client.put(
            "/api/whatsapp/settings",
            json={"enabled": True, "recipients": ["(31) 98318-1760"]},
        )
        assert resp.status_code == 200
        assert resp.json()["settings"]["recipients"] == [ATTENDANT]
        assert panel_env.save_settings.await_args.kwargs["updated_by"] == "admin"

    def test_rejects_invalid_number(self, panel_env):
        resp = client.put(
            "/api/whatsapp/settings", json={"enabled": True, "recipients": ["123"]}
        )
        assert resp.status_code == 422
        panel_env.save_settings.assert_not_awaited()

    def test_enabled_needs_a_number(self, panel_env):
        resp = client.put(
            "/api/whatsapp/settings", json={"enabled": True, "recipients": []}
        )
        assert resp.status_code == 422

    def test_status_without_wuzapi_configured(self, panel_env, monkeypatch):
        monkeypatch.setattr(settings, "wuzapi_api_url", "")
        panel_env.get_settings.return_value = NotifySettings(True, [], None, None)
        body = client.get("/api/whatsapp/status").json()
        assert body["connection"]["configured"] is False
        assert "WUZAPI_API_URL" in body["connection"]["error"]

    def test_requires_login(self):
        app.dependency_overrides.clear()
        assert client.get("/api/whatsapp/status").status_code == 401
