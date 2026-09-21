"""Testes da mídia por URL (attachments do Instagram) no pré-processamento."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.worker.media import (
    AUTO_RESPONSE_IMAGE_DISABLED,
    AUTO_RESPONSE_MEDIA_FAILURE,
    AUTO_RESPONSE_UNSUPPORTED_MEDIA,
    MediaDownloadError,
    _audio_format_from_media_type,
    download_media,
    preprocess_incoming_message,
)

IMAGE_URL = "https://cdn.example.com/image.jpg"
AUDIO_URL = "https://cdn.example.com/audio.mp4"


def _patch_download(*, content=b"bytes", content_type="image/jpeg", side_effect=None):
    return patch(
        "whatsapp_langchain.worker.media.download_media",
        new=AsyncMock(
            return_value=(content, content_type),
            side_effect=side_effect,
        ),
    )


class TestPreprocessFromUrl:
    async def test_image_url_downloaded_and_described(self):
        describe = AsyncMock(return_value="uma receita médica")
        with (
            _patch_download(content_type="image/png") as download,
            patch("whatsapp_langchain.worker.media._describe_image", new=describe),
        ):
            result = await preprocess_incoming_message(
                body="",
                media_type="image/*",
                media_url=IMAGE_URL,
            )

        download.assert_awaited_once_with(IMAGE_URL)
        # O MIME real (Content-Type do download) substitui o genérico "image/*".
        assert describe.await_args.args == (b"bytes", "image/png")
        assert result.should_invoke_agent is True
        assert result.media_processing_status == "processed"
        assert "[Descrição de imagem]: uma receita médica" in (
            result.normalized_text or ""
        )

    async def test_audio_url_downloaded_and_transcribed(self):
        transcribe = AsyncMock(return_value="quero marcar consulta")
        with (
            _patch_download(content_type="audio/mp4"),
            patch("whatsapp_langchain.worker.media._transcribe_audio", new=transcribe),
        ):
            result = await preprocess_incoming_message(
                body="",
                media_type="audio/*",
                media_url=AUDIO_URL,
            )

        assert transcribe.await_args.args[1] == "audio/mp4"
        assert result.media_processing_status == "processed"
        assert "[Transcrição de áudio]: quero marcar consulta" in (
            result.normalized_text or ""
        )

    async def test_generic_hint_falls_back_to_default_mime(self):
        describe = AsyncMock(return_value="x")
        with (
            _patch_download(content_type="application/octet-stream"),
            patch("whatsapp_langchain.worker.media._describe_image", new=describe),
        ):
            await preprocess_incoming_message(
                body="", media_type="image/*", media_url=IMAGE_URL
            )
        assert describe.await_args.args[1] == "image/jpeg"

    async def test_download_failure_returns_auto_response(self):
        with _patch_download(side_effect=MediaDownloadError("URL expirada")):
            result = await preprocess_incoming_message(
                body="", media_type="image/*", media_url=IMAGE_URL
            )
        assert result.should_invoke_agent is False
        assert result.media_processing_status == "failed"
        assert result.auto_response == AUTO_RESPONSE_MEDIA_FAILURE
        assert "URL expirada" in (result.media_processing_error or "")

    async def test_unsupported_type_does_not_download(self):
        with _patch_download() as download:
            result = await preprocess_incoming_message(
                body="", media_type="unsupported/share", media_url=None
            )
        download.assert_not_awaited()
        assert result.should_invoke_agent is False
        assert result.auto_response == AUTO_RESPONSE_UNSUPPORTED_MEDIA
        assert result.media_processing_status == "unsupported"

    async def test_disabled_image_does_not_download(self):
        with (
            patch.object(settings, "media_image_enabled", False),
            _patch_download() as download,
        ):
            result = await preprocess_incoming_message(
                body="", media_type="image/*", media_url=IMAGE_URL
            )
        download.assert_not_awaited()
        assert result.auto_response == AUTO_RESPONSE_IMAGE_DISABLED

    async def test_url_without_media_type_is_unsupported(self):
        result = await preprocess_incoming_message(
            body="", media_type=None, media_url=IMAGE_URL
        )
        assert result.should_invoke_agent is False
        assert result.media_processing_status == "unsupported"


def _client_with(handler):
    """Patch de httpx.AsyncClient para servir `handler` via MockTransport."""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self_client, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self_client, **kwargs)

    return patch.object(httpx.AsyncClient, "__init__", patched_init)


class TestDownloadMedia:
    async def test_downloads_bytes_and_content_type(self):
        def handler(request):
            return httpx.Response(
                200,
                content=b"\xff\xd8jpeg",
                headers={"content-type": "image/JPEG; x=1"},
            )

        with _client_with(handler):
            data, content_type = await download_media(IMAGE_URL)

        assert data == b"\xff\xd8jpeg"
        assert content_type == "image/jpeg"

    async def test_missing_content_type_returns_none(self):
        def handler(request):
            return httpx.Response(200, content=b"x")

        with _client_with(handler):
            _, content_type = await download_media(IMAGE_URL)
        assert content_type is None

    async def test_follows_redirects(self):
        def handler(request):
            if request.url.path == "/start":
                return httpx.Response(
                    302, headers={"location": "https://cdn.example.com/final"}
                )
            return httpx.Response(200, content=b"final")

        with _client_with(handler):
            data, _ = await download_media("https://cdn.example.com/start")
        assert data == b"final"

    async def test_rejects_non_https_url(self):
        with pytest.raises(MediaDownloadError, match="https"):
            await download_media("http://cdn.example.com/a.jpg")

    @pytest.mark.parametrize("status", [403, 404, 410])
    async def test_expired_url_raises_explicit_error(self, status):
        with _client_with(lambda request: httpx.Response(status)):
            with pytest.raises(MediaDownloadError, match="expirada"):
                await download_media(IMAGE_URL)

    async def test_server_error_raises(self):
        with _client_with(lambda request: httpx.Response(500)):
            with pytest.raises(MediaDownloadError, match="500"):
                await download_media(IMAGE_URL)

    async def test_declared_size_over_limit_raises(self):
        def handler(request):
            return httpx.Response(
                200, content=b"x", headers={"content-length": str(50 * 1024 * 1024)}
            )

        with _client_with(handler):
            with pytest.raises(MediaDownloadError, match="tamanho"):
                await download_media(IMAGE_URL)

    async def test_streamed_size_over_limit_raises(self):
        with (
            patch("whatsapp_langchain.worker.media.MAX_MEDIA_DOWNLOAD_BYTES", 10),
            _client_with(lambda request: httpx.Response(200, content=b"x" * 100)),
        ):
            with pytest.raises(MediaDownloadError, match="tamanho"):
                await download_media(IMAGE_URL)

    async def test_network_error_is_wrapped(self):
        def handler(request):
            raise httpx.ConnectTimeout("timeout", request=request)

        with _client_with(handler):
            with pytest.raises(MediaDownloadError, match="Falha ao baixar"):
                await download_media(IMAGE_URL)


class TestAudioFormat:
    def test_m4a_family_maps_to_m4a(self):
        assert _audio_format_from_media_type("audio/mp4") == "m4a"
        assert _audio_format_from_media_type("audio/x-m4a") == "m4a"

    def test_aac(self):
        assert _audio_format_from_media_type("audio/aac") == "aac"

    def test_existing_formats_unchanged(self):
        assert _audio_format_from_media_type("audio/mpeg") == "mp3"
        assert _audio_format_from_media_type("audio/ogg") == "ogg"
        assert _audio_format_from_media_type("audio/wav") == "wav"
