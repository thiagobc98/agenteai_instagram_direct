"""Testes do InstagramClient assíncrono.

Usa httpx mock para simular respostas da Graph API sem fazer chamadas HTTP
reais.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from whatsapp_langchain.worker.instagram_client import (
    MAX_MESSAGE_BYTES,
    InstagramClient,
    InstagramSendError,
    is_within_messaging_window,
    split_message,
    to_plain_text,
)

TEST_TOKEN = "test-access-token"
IGSID = "17841400000000001"


@pytest.fixture
def client():
    return InstagramClient(access_token=TEST_TOKEN, api_version="v25.0")


def mock_transport(status_code: int, body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=body)

    return httpx.MockTransport(handler)


def patch_async_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Substitui httpx.AsyncClient para usar o mock transport."""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self_client, **kwargs):
        kwargs["transport"] = transport
        original_init(self_client, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestInit:
    def test_builds_url_from_base_and_version(self, client):
        assert client.url == "https://graph.instagram.com/v25.0/me/messages"

    def test_custom_base_url_strips_trailing_slash(self):
        c = InstagramClient(TEST_TOKEN, "v24.0", "https://graph.facebook.com/")
        assert c.url == "https://graph.facebook.com/v24.0/me/messages"

    def test_sets_bearer_header(self, client):
        assert client.headers["Authorization"] == f"Bearer {TEST_TOKEN}"

    def test_rejects_empty_token(self):
        with pytest.raises(ValueError, match="access_token"):
            InstagramClient("")

    def test_rejects_empty_api_version(self):
        with pytest.raises(ValueError, match="api_version"):
            InstagramClient(TEST_TOKEN, api_version="")

    def test_rejects_empty_base_url(self):
        with pytest.raises(ValueError, match="base_url"):
            InstagramClient(TEST_TOKEN, base_url="")


class TestSendMessage:
    async def test_sends_message_successfully(self, client, monkeypatch):
        patch_async_client(
            monkeypatch,
            mock_transport(200, {"recipient_id": IGSID, "message_id": "MID123"}),
        )
        assert await client.send_message(IGSID, "Olá!") == "MID123"

    async def test_sends_correct_request(self, client, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"message_id": "MID123"})

        patch_async_client(monkeypatch, httpx.MockTransport(handler))
        await client.send_message(IGSID, "Olá!")

        assert captured["url"] == "https://graph.instagram.com/v25.0/me/messages"
        assert captured["auth"] == f"Bearer {TEST_TOKEN}"
        assert captured["json"] == {
            "recipient": {"id": IGSID},
            "message": {"text": "Olá!"},
        }

    async def test_returns_empty_string_when_no_id_in_response(
        self, client, monkeypatch
    ):
        patch_async_client(monkeypatch, mock_transport(200, {"recipient_id": IGSID}))
        assert await client.send_message(IGSID, "Olá!") == ""

    async def test_strips_markdown_before_sending(self, client, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"message_id": "M"})

        patch_async_client(monkeypatch, httpx.MockTransport(handler))
        await client.send_message(IGSID, "**Consulta** confirmada")
        assert captured["json"]["message"]["text"] == "Consulta confirmada"

    async def test_splits_long_message_in_several_requests(self, client, monkeypatch):
        sent: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content)["message"]["text"])
            return httpx.Response(200, json={"message_id": f"M{len(sent)}"})

        patch_async_client(monkeypatch, httpx.MockTransport(handler))
        body = "\n\n".join(f"Parágrafo {i}: " + "á" * 300 for i in range(6))

        last_id = await client.send_message(IGSID, body)

        assert len(sent) > 1
        assert last_id == f"M{len(sent)}"
        assert all(len(part.encode("utf-8")) <= MAX_MESSAGE_BYTES for part in sent)

    async def test_rejects_empty_body(self, client):
        with pytest.raises(ValueError, match="body"):
            await client.send_message(IGSID, "   ")

    async def test_raises_on_4xx_error(self, client, monkeypatch):
        patch_async_client(
            monkeypatch,
            mock_transport(
                400, {"error": {"message": "Invalid recipient", "code": 100}}
            ),
        )
        with pytest.raises(InstagramSendError) as exc_info:
            await client.send_message(IGSID, "Olá!")

        assert exc_info.value.status_code == 400
        assert exc_info.value.code == 100
        assert "Invalid recipient" in exc_info.value.detail

    async def test_raises_on_5xx_error(self, client, monkeypatch):
        patch_async_client(monkeypatch, mock_transport(500, {"error": {"code": 2}}))
        with pytest.raises(InstagramSendError) as exc_info:
            await client.send_message(IGSID, "Olá!")
        assert exc_info.value.status_code == 500

    async def test_raises_on_non_json_error_body(self, client, monkeypatch):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(502, text="Bad Gateway")
        )
        patch_async_client(monkeypatch, transport)
        with pytest.raises(InstagramSendError) as exc_info:
            await client.send_message(IGSID, "Olá!")
        assert exc_info.value.status_code == 502
        assert exc_info.value.detail == "Bad Gateway"
        assert exc_info.value.code is None

    async def test_token_expired_error_is_classified(self, client, monkeypatch):
        patch_async_client(
            monkeypatch,
            mock_transport(
                401,
                {"error": {"message": "Error validating access token", "code": 190}},
            ),
        )
        with pytest.raises(InstagramSendError) as exc_info:
            await client.send_message(IGSID, "Olá!")
        assert exc_info.value.is_token_invalid
        assert not exc_info.value.is_window_closed

    async def test_window_closed_error_is_classified(self, client, monkeypatch):
        patch_async_client(
            monkeypatch,
            mock_transport(
                400,
                {
                    "error": {
                        "message": "(#10) Message sent outside of allowed window.",
                        "code": 10,
                        "error_subcode": 2534022,
                    }
                },
            ),
        )
        with pytest.raises(InstagramSendError) as exc_info:
            await client.send_message(IGSID, "Olá!")
        assert exc_info.value.is_window_closed
        assert not exc_info.value.is_token_invalid

    async def test_rate_limit_error_is_classified(self, client, monkeypatch):
        patch_async_client(
            monkeypatch,
            mock_transport(400, {"error": {"message": "Rate limit", "code": 613}}),
        )
        with pytest.raises(InstagramSendError) as exc_info:
            await client.send_message(IGSID, "Olá!")
        assert exc_info.value.is_rate_limited

    async def test_http_429_is_rate_limited(self, client, monkeypatch):
        patch_async_client(monkeypatch, mock_transport(429, {}))
        with pytest.raises(InstagramSendError) as exc_info:
            await client.send_message(IGSID, "Olá!")
        assert exc_info.value.is_rate_limited


class TestSenderActions:
    async def test_typing_sends_typing_on(self, client, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"recipient_id": IGSID})

        patch_async_client(monkeypatch, httpx.MockTransport(handler))
        assert await client.send_typing(IGSID) is True
        assert captured["json"] == {
            "recipient": {"id": IGSID},
            "sender_action": "typing_on",
        }

    async def test_mark_seen_sends_mark_seen(self, client, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"recipient_id": IGSID})

        patch_async_client(monkeypatch, httpx.MockTransport(handler))
        assert await client.mark_seen(IGSID) is True
        assert captured["json"]["sender_action"] == "mark_seen"
        # A API exige só recipient + sender_action nessas requisições.
        assert set(captured["json"]) == {"recipient", "sender_action"}

    async def test_returns_false_on_http_error(self, client, monkeypatch):
        patch_async_client(monkeypatch, mock_transport(400, {"error": {"code": 100}}))
        assert await client.send_typing(IGSID) is False
        assert await client.mark_seen(IGSID) is False

    async def test_does_not_raise_on_exception(self, client, monkeypatch):
        def raise_init(self_client, **kwargs):
            raise Exception("network error")

        monkeypatch.setattr(httpx.AsyncClient, "__init__", raise_init)
        assert await client.send_typing(IGSID) is False
        assert await client.mark_seen(IGSID) is False


class TestSplitMessage:
    def test_short_text_is_a_single_part(self):
        assert split_message("Olá!") == ["Olá!"]

    def test_empty_text_has_no_parts(self):
        assert split_message("  \n ") == []

    def test_splits_on_paragraph_boundaries(self):
        p1, p2 = "a" * 600, "b" * 600
        assert split_message(f"{p1}\n\n{p2}") == [p1, p2]

    def test_splits_on_words_when_no_newlines(self):
        text = " ".join(["palavra"] * 300)
        parts = split_message(text)
        assert len(parts) > 1
        assert all(len(p.encode("utf-8")) <= MAX_MESSAGE_BYTES for p in parts)
        assert " ".join(parts) == text

    def test_hard_splits_unbroken_text_without_breaking_characters(self):
        text = "ç" * 1500  # 3000 bytes, sem nenhum separador
        parts = split_message(text)
        assert len(parts) > 1
        assert all(len(p.encode("utf-8")) <= MAX_MESSAGE_BYTES for p in parts)
        assert "".join(parts) == text

    def test_limit_is_in_bytes_not_characters(self):
        # 400 caracteres de 3 bytes = 1200 bytes > 1000
        text = "€" * 400
        assert len(split_message(text)) == 2

    def test_custom_limit(self):
        assert split_message("um dois três", limit=8) == ["um dois", "três"]


class TestToPlainText:
    def test_removes_bold_markers(self):
        assert (
            to_plain_text("**data**: 10/10 e __hora__: 9h") == "data: 10/10 e hora: 9h"
        )

    def test_removes_headings_and_backticks(self):
        assert to_plain_text("## Título\n`código`") == "Título\ncódigo"

    def test_keeps_plain_text_and_list_dashes(self):
        assert to_plain_text("- item 1\n- item 2") == "- item 1\n- item 2"


class TestMessagingWindow:
    NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    def test_within_window(self):
        assert is_within_messaging_window(self.NOW - timedelta(hours=3), self.NOW)

    def test_outside_window(self):
        assert not is_within_messaging_window(self.NOW - timedelta(hours=25), self.NOW)

    def test_safety_margin_before_24h(self):
        assert not is_within_messaging_window(
            self.NOW - timedelta(hours=23, minutes=58), self.NOW
        )

    def test_never_wrote_is_outside_window(self):
        assert not is_within_messaging_window(None, self.NOW)

    def test_naive_datetime_is_treated_as_utc(self):
        naive = (self.NOW - timedelta(hours=1)).replace(tzinfo=None)
        assert is_within_messaging_window(naive, self.NOW)
