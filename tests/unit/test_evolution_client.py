"""Testes do EvolutionClient assíncrono.

Usa httpx mock para simular respostas da Evolution API
sem fazer chamadas HTTP reais.
"""

import httpx
import pytest

from whatsapp_langchain.worker.evolution_client import (
    EvolutionClient,
    EvolutionSendError,
    _normalize_number,
)

TEST_BASE_URL = "https://evo.example.com"
TEST_API_KEY = "test-api-key"
TEST_INSTANCE = "test-instance"


@pytest.fixture
def client():
    """EvolutionClient com credenciais de teste."""
    return EvolutionClient(
        base_url=TEST_BASE_URL,
        api_key=TEST_API_KEY,
        instance=TEST_INSTANCE,
    )


def mock_transport(status_code: int, body: dict) -> httpx.MockTransport:
    """Cria um transport mock que retorna a resposta configurada."""

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


class TestNormalizeNumber:
    """Testes da normalização de número (remove '+' e não-dígitos)."""

    def test_strips_plus(self):
        assert _normalize_number("+5511999999999") == "5511999999999"

    def test_keeps_digits_only(self):
        assert _normalize_number("+55 (11) 99999-9999") == "5511999999999"


class TestEvolutionClientInit:
    """Testes de inicialização do cliente."""

    def test_stores_config(self, client):
        """Armazena base_url, api_key e instance."""
        assert client.base_url == TEST_BASE_URL
        assert client.api_key == TEST_API_KEY
        assert client.instance == TEST_INSTANCE

    def test_strips_trailing_slash_from_base_url(self):
        client = EvolutionClient(
            base_url="https://evo.example.com/",
            api_key=TEST_API_KEY,
            instance=TEST_INSTANCE,
        )
        assert client.base_url == "https://evo.example.com"

    def test_sets_apikey_header(self, client):
        """Header apikey é usado para autenticação (não Basic Auth)."""
        assert client.headers["apikey"] == TEST_API_KEY

    def test_rejects_empty_base_url(self):
        with pytest.raises(ValueError, match="base_url"):
            EvolutionClient("", TEST_API_KEY, TEST_INSTANCE)

    def test_rejects_empty_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            EvolutionClient(TEST_BASE_URL, "", TEST_INSTANCE)

    def test_rejects_empty_instance(self):
        with pytest.raises(ValueError, match="instance"):
            EvolutionClient(TEST_BASE_URL, TEST_API_KEY, "")


class TestSendMessage:
    """Testes do envio de mensagem via Evolution API (sendText)."""

    async def test_sends_message_successfully(self, client, monkeypatch):
        """Envia mensagem e retorna o id."""
        patch_async_client(
            monkeypatch,
            mock_transport(201, {"key": {"id": "MSG123"}, "status": "PENDING"}),
        )

        message_id = await client.send_message("+5511999999999", "Olá!")
        assert message_id == "MSG123"

    async def test_sends_correct_payload(self, client, monkeypatch):
        """Verifica URL, header apikey e payload JSON corretos."""
        captured_request = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request["url"] = str(request.url)
            captured_request["content"] = request.content.decode()
            captured_request["apikey"] = request.headers.get("apikey")
            return httpx.Response(201, json={"key": {"id": "MSG123"}})

        patch_async_client(monkeypatch, httpx.MockTransport(handler))

        await client.send_message("+5511999999999", "Olá!")

        assert (
            captured_request["url"]
            == f"{TEST_BASE_URL}/message/sendText/{TEST_INSTANCE}"
        )
        assert captured_request["apikey"] == TEST_API_KEY

        import json as _json

        payload = _json.loads(captured_request["content"])
        assert payload["number"] == "5511999999999"
        assert payload["text"] == "Olá!"

    async def test_returns_empty_string_when_no_id_in_response(
        self, client, monkeypatch
    ):
        """Não quebra se a resposta não tiver key.id."""
        patch_async_client(monkeypatch, mock_transport(201, {"status": "PENDING"}))
        message_id = await client.send_message("+5511999999999", "Olá!")
        assert message_id == ""

    async def test_raises_on_4xx_error(self, client, monkeypatch):
        """Levanta EvolutionSendError em erro 4xx."""
        patch_async_client(
            monkeypatch, mock_transport(400, {"message": "Invalid number"})
        )

        with pytest.raises(EvolutionSendError) as exc_info:
            await client.send_message("+invalid", "Olá!")

        assert exc_info.value.status_code == 400
        assert "Invalid number" in exc_info.value.detail

    async def test_raises_on_5xx_error(self, client, monkeypatch):
        """Levanta EvolutionSendError em erro 5xx."""
        patch_async_client(
            monkeypatch, mock_transport(500, {"message": "Internal Server Error"})
        )

        with pytest.raises(EvolutionSendError) as exc_info:
            await client.send_message("+5511999999999", "Olá!")

        assert exc_info.value.status_code == 500

    async def test_raises_on_401_auth_error(self, client, monkeypatch):
        """Levanta EvolutionSendError com apikey inválida."""
        patch_async_client(
            monkeypatch, mock_transport(401, {"message": "Unauthorized"})
        )

        with pytest.raises(EvolutionSendError) as exc_info:
            await client.send_message("+5511999999999", "Olá!")

        assert exc_info.value.status_code == 401


class TestSendTyping:
    """Testes do indicador de digitação (best-effort)."""

    async def test_sends_typing_successfully(self, client, monkeypatch):
        """Typing faz POST em /chat/sendPresence e retorna True."""
        patch_async_client(monkeypatch, mock_transport(200, {"success": True}))

        result = await client.send_typing("+5511999999999")
        assert result is True

    async def test_sends_correct_presence_payload(self, client, monkeypatch):
        """Verifica payload de presence (composing + delay)."""
        captured_request = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request["url"] = str(request.url)
            captured_request["content"] = request.content.decode()
            return httpx.Response(200, json={"success": True})

        patch_async_client(monkeypatch, httpx.MockTransport(handler))

        await client.send_typing("+5511999999999", duration_ms=2000)

        assert (
            captured_request["url"]
            == f"{TEST_BASE_URL}/chat/sendPresence/{TEST_INSTANCE}"
        )

        import json as _json

        payload = _json.loads(captured_request["content"])
        assert payload["presence"] == "composing"
        assert payload["delay"] == 2000

    async def test_returns_false_on_error(self, client, monkeypatch):
        """Typing retorna False em erro HTTP (best-effort, sem exceção)."""
        patch_async_client(monkeypatch, mock_transport(400, {"error": "bad request"}))

        result = await client.send_typing("+5511999999999")
        assert result is False

    async def test_does_not_raise_on_exception(self, client, monkeypatch):
        """Typing nunca levanta exceção (best-effort)."""

        def raise_init(self_client, **kwargs):
            raise Exception("network error")

        monkeypatch.setattr(httpx.AsyncClient, "__init__", raise_init)

        result = await client.send_typing("+5511999999999")
        assert result is False
