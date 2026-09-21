"""Testes do filtro que esconde do modelo respostas antigas da persona errada."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from whatsapp_langchain.agents.catalog.secretaria.agent import STALE_REPLY_MARKERS
from whatsapp_langchain.agents.middleware.stale_history import (
    create_stale_history_filter,
    drop_stale_messages,
)

MARKERS = ("Dra. Luana Lima",)
OLD_REPLY = (
    "Boa tarde! Aqui quem fala é a secretária da Dra. Luana Lima, seja "
    "bem-vindo(a). O que posso ajudar você hoje?"
)


class TestDropStaleMessages:
    def test_removes_old_persona_reply_and_keeps_the_rest(self):
        history = [
            HumanMessage("Oi"),
            AIMessage(OLD_REPLY),
            HumanMessage("Quem tá falando?"),
            AIMessage("Sou a Juliana, atendente virtual da Patricia Berberich."),
        ]

        cleaned = drop_stale_messages(history, MARKERS)

        assert [m.content for m in cleaned] == [
            "Oi",
            "Quem tá falando?",
            "Sou a Juliana, atendente virtual da Patricia Berberich.",
        ]

    def test_match_ignores_case(self):
        history = [AIMessage("aqui é a DRA. LUANA LIMA")]

        assert drop_stale_messages(history, MARKERS) == []

    def test_never_touches_customer_messages(self):
        history = [HumanMessage("A Dra. Luana Lima atende aí?")]

        assert drop_stale_messages(history, MARKERS) == history

    def test_keeps_assistant_messages_that_call_tools(self):
        with_tool = AIMessage(
            OLD_REPLY,
            tool_calls=[{"name": "read_memory", "args": {}, "id": "call-1"}],
        )
        history = [with_tool, ToolMessage("ok", tool_call_id="call-1")]

        assert drop_stale_messages(history, MARKERS) == history

    def test_history_without_markers_is_unchanged(self):
        history = [HumanMessage("Oi"), AIMessage("Boa tarde!")]

        assert drop_stale_messages(history, MARKERS) == history

    def test_handles_list_content(self):
        history = [AIMessage([{"type": "text", "text": OLD_REPLY}])]

        assert drop_stale_messages(history, MARKERS) == []


class TestMiddleware:
    def test_overrides_request_only_when_something_is_dropped(self):
        middleware = create_stale_history_filter(MARKERS)
        request = MagicMock()
        request.messages = [HumanMessage("Oi"), AIMessage(OLD_REPLY)]
        handler = MagicMock(return_value="resposta")

        assert middleware.wrap_model_call(request, handler) == "resposta"

        request.override.assert_called_once()
        kept = request.override.call_args.kwargs["messages"]
        assert [m.content for m in kept] == ["Oi"]
        handler.assert_called_once_with(request.override.return_value)

    def test_passes_request_through_when_history_is_clean(self):
        middleware = create_stale_history_filter(MARKERS)
        request = MagicMock()
        request.messages = [HumanMessage("Oi")]
        handler = MagicMock(return_value="ok")

        middleware.wrap_model_call(request, handler)

        request.override.assert_not_called()
        handler.assert_called_once_with(request)

    async def test_async_path_filters_too(self):
        middleware = create_stale_history_filter(MARKERS)
        request = MagicMock()
        request.messages = [AIMessage(OLD_REPLY), HumanMessage("Oi")]

        async def handler(req):
            return req

        result = await middleware.awrap_model_call(request, handler)

        assert result is request.override.return_value


def test_agent_registers_the_luana_marker():
    assert "Dra. Luana Lima" in STALE_REPLY_MARKERS
