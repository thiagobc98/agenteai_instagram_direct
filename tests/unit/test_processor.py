"""Testes do fluxo send_message → mark_done / mark_failed no processor.

Garante que:
- mark_done NÃO roda quando send_message falha
- mark_failed É chamado no erro de envio
- auto-response de mídia também respeita a regra (envia antes de mark_done)
- Falha no auto-response entra em retry via mark_failed
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from whatsapp_langchain.shared.models import MessageQueue
from whatsapp_langchain.worker.instagram_client import InstagramSendError
from whatsapp_langchain.worker.media import MediaPreprocessResult

# --- Fixtures ---


@pytest.fixture
def message():
    """Mensagem de texto padrão para testes."""
    return MessageQueue(
        id=1,
        message_id="MSG123",
        external_id="17841400000000001",
        agent_id="secretaria",
        thread_id="17841400000000001:secretaria",
        incoming_message="Olá!",
    )


@pytest.fixture
def media_message():
    """Mensagem com mídia desabilitada/falha para testar auto-response."""
    return MessageQueue(
        id=2,
        message_id="MSG456",
        external_id="17841400000000001",
        agent_id="secretaria",
        thread_id="17841400000000001:secretaria",
        incoming_message="",
        media_base64="aGVsbG8=",
        media_type="image/jpeg",
    )


@pytest.fixture
def mock_instagram():
    """InstagramClient mock com send_message, send_typing e mark_seen."""
    instagram = AsyncMock()
    instagram.send_typing = AsyncMock(return_value=True)
    instagram.mark_seen = AsyncMock(return_value=True)
    instagram.send_message = AsyncMock(return_value="MSG_RESPONSE_123")
    return instagram


# --- Fixtures ---


@pytest.fixture(autouse=True)
def mock_get_username():
    """Por padrão, contato sem @ salvo (não afeta os testes que não olham isso)."""
    with patch(
        "whatsapp_langchain.worker.processor.get_contact_username",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock:
        yield mock


# --- Helpers ---


def _patch_processor(preprocess_result):
    """Retorna context managers para mockar dependências do processor."""
    return (
        patch(
            "whatsapp_langchain.worker.processor.preprocess_incoming_message",
            new_callable=AsyncMock,
            return_value=preprocess_result,
        ),
        patch("whatsapp_langchain.worker.processor.load_graph"),
        patch(
            "whatsapp_langchain.worker.processor.mark_done",
            new_callable=AsyncMock,
        ),
        patch(
            "whatsapp_langchain.worker.processor.mark_failed",
            new_callable=AsyncMock,
        ),
        patch(
            "whatsapp_langchain.worker.processor.upsert_conversation",
            new_callable=AsyncMock,
        ),
    )


TEXT_PREPROCESS = MediaPreprocessResult(
    should_invoke_agent=True,
    normalized_text="Olá!",
    media_processing_status="none",
)

MEDIA_DISABLED_PREPROCESS = MediaPreprocessResult(
    should_invoke_agent=False,
    normalized_text=None,
    media_processing_status="disabled",
    auto_response="Imagens estão desabilitadas neste momento.",
)


# === Testes do fluxo normal (texto) ===


class TestSendMessageMarkDone:
    """Garante que mark_done só ocorre após send_message bem-sucedido."""

    async def test_mark_done_after_successful_send(self, message, mock_instagram):
        """Fluxo feliz: send_message ok → mark_done chamado."""
        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2] as mock_done,
            patches[3] as mock_failed,
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {
                "messages": [MagicMock(content="Resposta do agente")]
            }
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

            # send_message chamado com a resposta do agente
            mock_instagram.send_message.assert_awaited_once_with(
                "17841400000000001", "Resposta do agente"
            )
            # mark_done chamado
            assert mock_done.await_count == 1
            # mark_failed NÃO chamado
            mock_failed.assert_not_awaited()

    async def test_mark_done_not_called_when_send_fails(self, message, mock_instagram):
        """send_message falha → mark_done NÃO é chamado, mark_failed SIM."""
        mock_instagram.send_message = AsyncMock(
            side_effect=InstagramSendError(500, "Internal Server Error")
        )

        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2] as mock_done,
            patches[3] as mock_failed,
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {
                "messages": [MagicMock(content="Resposta do agente")]
            }
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

            # send_message foi chamado (e falhou)
            mock_instagram.send_message.assert_awaited_once()
            # mark_done NÃO chamado
            mock_done.assert_not_awaited()
            # mark_failed chamado com o erro
            mock_failed.assert_awaited_once()
            error_arg = mock_failed.call_args[0][2]
            assert "500" in error_arg

    async def test_mark_failed_on_generic_send_exception(self, message, mock_instagram):
        """Exceção genérica no send_message → mark_failed."""
        mock_instagram.send_message = AsyncMock(
            side_effect=Exception("Connection timeout")
        )

        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2] as mock_done,
            patches[3] as mock_failed,
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {
                "messages": [MagicMock(content="Resposta")]
            }
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

            mock_done.assert_not_awaited()
            mock_failed.assert_awaited_once()
            assert "Connection timeout" in mock_failed.call_args[0][2]


# === Testes do fluxo auto-response (mídia) ===


class TestAutoResponseInstagram:
    """Garante que auto-response de mídia também envia antes de mark_done."""

    async def test_auto_response_sends_via_instagram(
        self, media_message, mock_instagram
    ):
        """Auto-response de mídia desabilitada envia antes de mark_done."""
        patches = _patch_processor(MEDIA_DISABLED_PREPROCESS)
        with (
            patches[0],
            patches[1],
            patches[2] as mock_done,
            patches[3] as mock_failed,
            patches[4],
        ):
            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                media_message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

            # Auto-response enviada via Instagram
            mock_instagram.send_message.assert_awaited_once_with(
                "17841400000000001",
                "Imagens estão desabilitadas neste momento.",
            )
            # mark_done chamado após envio
            assert mock_done.await_count == 1
            mock_failed.assert_not_awaited()

    async def test_auto_response_mark_failed_when_send_fails(
        self, media_message, mock_instagram
    ):
        """Auto-response falha no envio → mark_failed (retry)."""
        mock_instagram.send_message = AsyncMock(
            side_effect=InstagramSendError(503, "Service Unavailable")
        )

        patches = _patch_processor(MEDIA_DISABLED_PREPROCESS)
        with (
            patches[0],
            patches[1],
            patches[2] as mock_done,
            patches[3] as mock_failed,
            patches[4],
        ):
            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                media_message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

            # send_message foi chamado (e falhou)
            mock_instagram.send_message.assert_awaited_once()
            # mark_done NÃO chamado
            mock_done.assert_not_awaited()
            # mark_failed chamado
            mock_failed.assert_awaited_once()
            assert "503" in mock_failed.call_args[0][2]


# === Testes específicos do canal Instagram ===


class TestInstagramChannel:
    """Mark-seen/typing, mídia por URL e identidade do contato."""

    async def test_marks_seen_and_types_before_running_agent(
        self, message, mock_instagram
    ):
        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2],
            patches[3],
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {"messages": [MagicMock(content="Oi")]}
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

        mock_instagram.mark_seen.assert_awaited_once_with("17841400000000001")
        mock_instagram.send_typing.assert_awaited_once_with("17841400000000001")

    async def test_mark_seen_failure_does_not_block_reply(
        self, message, mock_instagram
    ):
        mock_instagram.mark_seen = AsyncMock(side_effect=RuntimeError("boom"))

        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2] as mock_done,
            patches[3] as mock_failed,
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {"messages": [MagicMock(content="Oi")]}
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

        mock_instagram.send_message.assert_awaited_once()
        mock_done.assert_awaited_once()
        mock_failed.assert_not_awaited()

    async def test_passes_media_url_to_preprocessing(self, mock_instagram):
        message = MessageQueue(
            id=3,
            message_id="MID3",
            external_id="17841400000000001",
            agent_id="secretaria",
            thread_id="17841400000000001:secretaria",
            incoming_message="",
            media_url="https://cdn.example.com/i.jpg",
            media_type="image/*",
        )
        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0] as mock_preprocess,
            patches[1] as mock_load,
            patches[2],
            patches[3],
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {"messages": [MagicMock(content="Ok")]}
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

        kwargs = mock_preprocess.await_args.kwargs
        assert kwargs["media_url"] == "https://cdn.example.com/i.jpg"
        assert kwargs["media_type"] == "image/*"

    async def test_agent_runs_with_external_id_as_user_id(
        self, message, mock_instagram
    ):
        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2],
            patches[3],
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {"messages": [MagicMock(content="Oi")]}
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

        config = mock_graph.ainvoke.await_args.kwargs["config"]
        assert config["configurable"] == {
            "thread_id": "17841400000000001:secretaria",
            "user_id": "17841400000000001",
        }

    async def test_agent_receives_the_contact_username_for_the_greeting(
        self, message, mock_instagram, mock_get_username
    ):
        """O @ salvo do contato (tabela contacts) chega ao estado do grafo."""
        mock_get_username.return_value = "_thibec"
        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2],
            patches[3],
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {"messages": [MagicMock(content="Oi")]}
            mock_load.return_value = mock_graph
            pool = AsyncMock()

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                pool,
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

        mock_get_username.assert_awaited_once_with(pool, "17841400000000001")
        state_input = mock_graph.ainvoke.await_args.args[0]
        assert state_input["username"] == "_thibec"

    async def test_agent_receives_none_when_contact_has_no_username_yet(
        self, message, mock_instagram
    ):
        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2],
            patches[3],
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {"messages": [MagicMock(content="Oi")]}
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

        state_input = mock_graph.ainvoke.await_args.args[0]
        assert state_input["username"] is None

    async def test_window_closed_send_error_goes_to_retry_flow(
        self, message, mock_instagram
    ):
        mock_instagram.send_message = AsyncMock(
            side_effect=InstagramSendError(
                400, "outside of allowed window", code=10, subcode=2534022
            )
        )
        patches = _patch_processor(TEXT_PREPROCESS)
        with (
            patches[0],
            patches[1] as mock_load,
            patches[2] as mock_done,
            patches[3] as mock_failed,
            patches[4],
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {"messages": [MagicMock(content="Oi")]}
            mock_load.return_value = mock_graph

            from whatsapp_langchain.worker.processor import process_message

            await process_message(
                message,
                AsyncMock(),
                checkpointer=AsyncMock(),
                instagram=mock_instagram,
            )

        mock_done.assert_not_awaited()
        mock_failed.assert_awaited_once()
