"""Testes da publicação no Instagram (Feed, Story, Reels).

Cobrem as regras da Meta, o armazenamento da mídia, o parser da legenda da
IA e a máquina de estados do publicador (incluindo idempotência: nunca
publicar em dobro).
"""

import io
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from whatsapp_langchain.agents.captions import CaptionParseError, parse_caption
from whatsapp_langchain.server.main import app
from whatsapp_langchain.shared import media_storage
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.publishing import MediaInfo, validate_publication
from whatsapp_langchain.worker import publisher
from whatsapp_langchain.worker.instagram_client import InstagramSendError

IMG_SQUARE = MediaInfo("image", 1080, 1080)
IMG_PORTRAIT = MediaInfo("image", 1080, 1350)
IMG_TOO_TALL = MediaInfo("image", 1080, 1920)
VIDEO_VERTICAL = MediaInfo(
    "video", 1080, 1920, duration_seconds=20, size_bytes=10_000_000
)


# ---------------------------------------------------------------------------
# Regras da Meta
# ---------------------------------------------------------------------------


class TestValidation:
    def test_feed_single_image_ok(self):
        assert validate_publication("feed", "Legenda", [IMG_SQUARE]).ok

    def test_feed_carousel_ok(self):
        assert validate_publication("feed", "x", [IMG_SQUARE, VIDEO_VERTICAL]).ok

    def test_feed_requires_media(self):
        assert not validate_publication("feed", "x", []).ok

    def test_feed_single_video_must_be_reels(self):
        v = validate_publication("feed", "x", [VIDEO_VERTICAL])
        assert any("Reels" in e for e in v.errors)

    def test_feed_rejects_9_16_photo(self):
        v = validate_publication("feed", "x", [IMG_TOO_TALL])
        assert any("proporção" in e for e in v.errors)

    def test_feed_carousel_max_10(self):
        assert not validate_publication("feed", "x", [IMG_SQUARE] * 11).ok

    def test_carousel_mixed_ratios_warns(self):
        v = validate_publication("feed", "x", [IMG_SQUARE, IMG_PORTRAIT])
        assert v.ok and v.warnings

    def test_reels_needs_one_video(self):
        assert validate_publication("reels", "x", [VIDEO_VERTICAL]).ok
        assert not validate_publication("reels", "x", [IMG_SQUARE]).ok
        assert not validate_publication("reels", "x", [VIDEO_VERTICAL] * 2).ok

    def test_reels_duration_limits(self):
        short = MediaInfo("video", 1080, 1920, duration_seconds=2)
        assert not validate_publication("reels", "x", [short]).ok

    def test_story_single_media_and_caption_warning(self):
        v = validate_publication("story", "texto", [IMG_TOO_TALL])
        assert v.ok
        assert any("legenda" in w for w in v.warnings)
        assert not validate_publication("story", "", [IMG_SQUARE, IMG_SQUARE]).ok

    def test_story_video_over_60s(self):
        long = MediaInfo("video", 1080, 1920, duration_seconds=61)
        assert not validate_publication("story", "", [long]).ok

    def test_caption_limits(self):
        assert not validate_publication("feed", "a" * 2201, [IMG_SQUARE]).ok
        tags = " ".join(f"#t{i}" for i in range(31))
        assert not validate_publication("feed", tags, [IMG_SQUARE]).ok
        mentions = " ".join(f"@u{i}" for i in range(21))
        assert not validate_publication("feed", mentions, [IMG_SQUARE]).ok

    def test_email_is_not_a_mention(self):
        caption = " ".join(f"a{i}@loja.com" for i in range(25))
        assert validate_publication("feed", caption, [IMG_SQUARE]).ok


# ---------------------------------------------------------------------------
# Armazenamento
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "public_base_url", "https://loja.exemplo.com")
    return tmp_path


def _png(width=800, height=1000, mode="RGBA") -> io.BytesIO:
    buf = io.BytesIO()
    Image.new(mode, (width, height), (200, 10, 10, 128)).save(buf, "PNG")
    buf.seek(0)
    return buf


class TestStorage:
    def test_png_becomes_jpeg(self, storage):
        stored = media_storage.store_media(_png(), "image/png")
        assert stored.media_kind == "image"
        assert stored.content_type == "image/jpeg"
        assert stored.token.endswith(".jpg")
        assert (stored.width, stored.height) == (800, 1000)
        with Image.open(storage / stored.token) as img:
            assert img.format == "JPEG"

    def test_large_image_is_downscaled(self, storage):
        stored = media_storage.store_media(_png(4000, 5000, "RGB"), "image/png")
        assert max(stored.width, stored.height) == 1440

    def test_video_detected_by_ftyp(self, storage):
        data = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 5000
        stored = media_storage.store_media(io.BytesIO(data), "application/octet-stream")
        assert stored.media_kind == "video"
        assert stored.token.endswith(".mp4")
        assert (storage / stored.token).read_bytes() == data

    def test_quicktime(self, storage):
        data = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 100
        assert media_storage.store_media(io.BytesIO(data), None).token.endswith(".mov")

    def test_video_over_limit_rejected_and_cleaned(self, storage, monkeypatch):
        monkeypatch.setattr(settings, "media_max_upload_mb", 1)
        data = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (2 * 1024 * 1024)
        with pytest.raises(media_storage.MediaRejectedError):
            media_storage.store_media(io.BytesIO(data), None)
        assert list(storage.iterdir()) == []

    def test_garbage_rejected(self, storage):
        with pytest.raises(media_storage.MediaRejectedError):
            media_storage.store_media(io.BytesIO(b"not an image at all"), None)
        with pytest.raises(media_storage.MediaRejectedError):
            media_storage.store_media(io.BytesIO(b""), None)

    @pytest.mark.parametrize(
        "token", ["../secret.jpg", "a/b.jpg", "x.png", "x.jpg.exe", ".jpg", "x"]
    )
    def test_token_cannot_escape_folder(self, storage, token):
        assert media_storage.media_path(token) is None

    def test_public_url_problems(self, monkeypatch):
        monkeypatch.setattr(settings, "public_base_url", "")
        assert media_storage.public_base_url_problem()
        monkeypatch.setattr(settings, "public_base_url", "http://loja.com")
        assert media_storage.public_base_url_problem()
        monkeypatch.setattr(settings, "public_base_url", "https://localhost:8000")
        assert media_storage.public_base_url_problem()
        monkeypatch.setattr(settings, "public_base_url", "https://loja.com/")
        assert media_storage.public_base_url_problem() is None
        assert media_storage.public_url("abc.jpg") == "https://loja.com/media/abc.jpg"


class TestPublicMediaRoute:
    def test_serves_file_without_login(self, storage):
        stored = media_storage.store_media(_png(), "image/png")
        client = TestClient(app)
        r = client.get(f"/media/{stored.token}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert client.head(f"/media/{stored.token}").status_code == 200

    def test_unknown_or_malicious_token_404(self, storage):
        client = TestClient(app)
        assert client.get("/media/nope.jpg").status_code == 404
        assert client.get("/media/..%2F..%2Fetc%2Fpasswd").status_code == 404


# ---------------------------------------------------------------------------
# Legenda da IA
# ---------------------------------------------------------------------------


class TestCaptionParse:
    def test_basic(self):
        d = parse_caption(
            '{"caption": "Scarpin nude ✨", "hashtags": ["#scarpin", "bh"], '
            '"notes": "ok"}'
        )
        assert d.caption == "Scarpin nude ✨"
        assert d.hashtags == ["#patriciaberberich", "#scarpin", "#bh"]
        assert d.full_text == "Scarpin nude ✨\n\n#patriciaberberich #scarpin #bh"
        assert d.notes == "ok"

    def test_inline_hashtags_moved_and_deduplicated(self):
        d = parse_caption(
            '{"caption": "Lindo #Scarpin", '
            '"hashtags": ["#scarpin", "#patriciaberberich"]}'
        )
        assert d.caption == "Lindo"
        assert [t.lower() for t in d.hashtags] == ["#scarpin", "#patriciaberberich"]

    def test_markdown_removed(self):
        assert parse_caption('{"caption": "**Novo** modelo"}').caption == "Novo modelo"

    def test_hashtags_capped_at_30(self):
        tags = [f"#t{i}" for i in range(50)]
        d = parse_caption(
            '{"caption": "x", "hashtags": ' + str(tags).replace("'", '"') + "}"
        )
        assert len(d.hashtags) == 30

    def test_never_exceeds_2200(self):
        d = parse_caption('{"caption": "' + "palavra " * 400 + '", "hashtags": ["#a"]}')
        assert len(d.full_text) <= 2200

    def test_invalid(self):
        with pytest.raises(CaptionParseError):
            parse_caption("Aqui está sua legenda!")
        with pytest.raises(CaptionParseError):
            parse_caption('{"caption": ""}')


# ---------------------------------------------------------------------------
# Parâmetros dos containers
# ---------------------------------------------------------------------------


def _pub(kind="feed", media=None, status="scheduled", **extra) -> dict:
    pub = {
        "id": 1,
        "kind": kind,
        "status": status,
        "caption": "Legenda",
        "share_to_feed": True,
        "attempts": 0,
        "container_id": None,
        "container_created_at": None,
        "media": media
        or [
            {
                "id": 10,
                "token": "img.jpg",
                "media_kind": "image",
                "width": 1080,
                "height": 1080,
                "duration_seconds": None,
                "size_bytes": 1000,
                "container_id": None,
            }
        ],
    }
    pub.update(extra)
    return pub


def _video(media_id=20, container_id=None) -> dict:
    return {
        "id": media_id,
        "token": f"v{media_id}.mp4",
        "media_kind": "video",
        "width": 1080,
        "height": 1920,
        "duration_seconds": 20.0,
        "size_bytes": 10_000_000,
        "container_id": container_id,
    }


class TestContainerParams:
    @pytest.fixture(autouse=True)
    def _base(self, monkeypatch):
        monkeypatch.setattr(settings, "public_base_url", "https://loja.com")

    def test_feed_image(self):
        children, params = publisher.build_container_params(_pub())
        assert children == []
        assert params == {
            "image_url": "https://loja.com/media/img.jpg",
            "caption": "Legenda",
        }

    def test_story(self):
        _, params = publisher.build_container_params(_pub("story", [_video()]))
        assert params == {
            "media_type": "STORIES",
            "video_url": "https://loja.com/media/v20.mp4",
        }

    def test_reels(self):
        _, params = publisher.build_container_params(
            _pub("reels", [_video()], share_to_feed=False)
        )
        assert params["media_type"] == "REELS"
        assert params["share_to_feed"] is False
        assert params["caption"] == "Legenda"

    def test_carousel(self):
        pub = _pub(media=[_pub()["media"][0], _video()])
        children, params = publisher.build_container_params(pub)
        assert params is None
        assert children[0] == {
            "image_url": "https://loja.com/media/img.jpg",
            "is_carousel_item": True,
        }
        assert children[1]["media_type"] == "VIDEO"
        assert publisher.carousel_params(pub, ["a", "b"])["children"] == "a,b"


# ---------------------------------------------------------------------------
# Máquina de estados do publicador
# ---------------------------------------------------------------------------


@pytest.fixture
def worker_env(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://loja.com")
    monkeypatch.setattr(publisher, "_ig_user_id", "IGUSER")
    ig = AsyncMock()
    ig.publishing_quota.return_value = (3, 100)
    ig.create_container.return_value = "CONT1"
    ig.container_status.return_value = ("FINISHED", "")
    ig.publish_container.return_value = "MEDIA1"
    ig.get_media.return_value = {"permalink": "https://instagram.com/p/x"}
    store = AsyncMock()
    with patch.object(publisher, "store") as store_mod:
        # Funções puras continuam as reais
        from whatsapp_langchain.shared import publishing as real

        store_mod.validate_publication = real.validate_publication
        store_mod.media_info = real.media_info
        for name in (
            "claim_due",
            "set_processing",
            "check_again_in",
            "set_publishing",
            "mark_published",
            "mark_failed",
            "postpone",
            "set_child_container",
        ):
            setattr(store_mod, name, getattr(store, name))
        yield ig, store


POOL = object()


class TestPublisher:
    async def test_nothing_due(self, worker_env):
        ig, store = worker_env
        store.claim_due.return_value = None
        assert await publisher.publish_next(POOL, ig) is False

    async def test_scheduled_creates_container(self, worker_env):
        ig, store = worker_env
        store.claim_due.return_value = _pub()
        assert await publisher.publish_next(POOL, ig)
        ig.create_container.assert_awaited_once_with(
            "IGUSER",
            {"image_url": "https://loja.com/media/img.jpg", "caption": "Legenda"},
        )
        store.set_processing.assert_awaited_once_with(POOL, 1, "CONT1", 3)
        ig.publish_container.assert_not_awaited()

    async def test_missing_public_url_fails_before_meta(self, worker_env, monkeypatch):
        ig, store = worker_env
        monkeypatch.setattr(settings, "public_base_url", "")
        store.claim_due.return_value = _pub()
        await publisher.publish_next(POOL, ig)
        store.mark_failed.assert_awaited_once()
        ig.create_container.assert_not_awaited()

    async def test_invalid_publication_fails(self, worker_env):
        ig, store = worker_env
        store.claim_due.return_value = _pub("reels")  # reels com foto
        await publisher.publish_next(POOL, ig)
        store.mark_failed.assert_awaited_once()
        ig.create_container.assert_not_awaited()

    async def test_quota_exhausted_postpones(self, worker_env):
        ig, store = worker_env
        ig.publishing_quota.return_value = (100, 100)
        store.claim_due.return_value = _pub()
        await publisher.publish_next(POOL, ig)
        store.postpone.assert_awaited_once()
        assert store.postpone.await_args.args[2] == publisher.QUOTA_RETRY_SECONDS
        ig.create_container.assert_not_awaited()

    async def test_carousel_waits_for_video_items(self, worker_env):
        ig, store = worker_env
        ig.create_container.side_effect = ["C_IMG", "C_VID"]
        ig.container_status.return_value = ("IN_PROGRESS", "")
        pub = _pub(media=[_pub()["media"][0], _video()])
        store.claim_due.return_value = pub
        await publisher.publish_next(POOL, ig)
        assert store.set_child_container.await_count == 2
        store.check_again_in.assert_awaited_once()
        store.set_processing.assert_not_awaited()

    async def test_carousel_reuses_children_and_creates_parent(self, worker_env):
        ig, store = worker_env
        img = {**_pub()["media"][0], "container_id": "C_IMG"}
        pub = _pub(media=[img, _video(container_id="C_VID")])
        store.claim_due.return_value = pub
        await publisher.publish_next(POOL, ig)
        ig.create_container.assert_awaited_once()
        params = ig.create_container.await_args.args[1]
        assert params["media_type"] == "CAROUSEL"
        assert params["children"] == "C_IMG,C_VID"
        store.set_processing.assert_awaited_once_with(POOL, 1, "CONT1", 15)

    async def test_processing_finished_publishes(self, worker_env):
        ig, store = worker_env
        now = datetime.now(UTC).isoformat()
        store.claim_due.return_value = _pub(
            status="processing", container_id="CONT1", container_created_at=now
        )
        await publisher.publish_next(POOL, ig)
        store.set_publishing.assert_awaited_once()
        ig.publish_container.assert_awaited_once_with("IGUSER", "CONT1")
        store.mark_published.assert_awaited_once_with(
            POOL, 1, ig_media_id="MEDIA1", permalink="https://instagram.com/p/x"
        )

    async def test_processing_in_progress_checks_later(self, worker_env):
        ig, store = worker_env
        ig.container_status.return_value = ("IN_PROGRESS", "")
        store.claim_due.return_value = _pub(
            status="processing",
            container_id="CONT1",
            container_created_at=datetime.now(UTC).isoformat(),
        )
        await publisher.publish_next(POOL, ig)
        store.check_again_in.assert_awaited_once()
        ig.publish_container.assert_not_awaited()

    async def test_processing_timeout_fails(self, worker_env):
        ig, store = worker_env
        ig.container_status.return_value = ("IN_PROGRESS", "")
        old = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
        store.claim_due.return_value = _pub(
            status="processing", container_id="CONT1", container_created_at=old
        )
        await publisher.publish_next(POOL, ig)
        store.mark_failed.assert_awaited_once()

    async def test_meta_error_fails_with_message(self, worker_env):
        ig, store = worker_env
        ig.container_status.return_value = ("ERROR", "Unsupported codec")
        store.claim_due.return_value = _pub(
            status="processing",
            container_id="CONT1",
            container_created_at=datetime.now(UTC).isoformat(),
        )
        await publisher.publish_next(POOL, ig)
        assert "Unsupported codec" in store.mark_failed.await_args.args[2]

    async def test_already_published_is_not_published_again(self, worker_env):
        """Processo caiu depois do media_publish: não pode publicar em dobro."""
        ig, store = worker_env
        ig.container_status.return_value = ("PUBLISHED", "")
        ig.list_media.return_value = [
            {"id": "M9", "caption": "Legenda", "permalink": "P"}
        ]
        store.claim_due.return_value = _pub(
            status="publishing",
            container_id="CONT1",
            container_created_at=datetime.now(UTC).isoformat(),
        )
        await publisher.publish_next(POOL, ig)
        ig.publish_container.assert_not_awaited()
        store.mark_published.assert_awaited_once_with(
            POOL, 1, ig_media_id="M9", permalink="P"
        )

    async def test_transient_error_on_publish_rechecks_container(self, worker_env):
        ig, store = worker_env
        ig.publish_container.side_effect = InstagramSendError(503, "unavailable")
        store.claim_due.return_value = _pub(
            status="processing",
            container_id="CONT1",
            container_created_at=datetime.now(UTC).isoformat(),
        )
        await publisher.publish_next(POOL, ig)
        store.check_again_in.assert_awaited_once()
        assert store.check_again_in.await_args.kwargs["count_attempt"] is True
        store.postpone.assert_not_awaited()  # não recria o container

    async def test_transient_error_on_publish_gives_up_with_warning(self, worker_env):
        ig, store = worker_env
        ig.publish_container.side_effect = InstagramSendError(503, "unavailable")
        store.claim_due.return_value = _pub(
            status="publishing",
            container_id="CONT1",
            attempts=publisher.MAX_TRANSIENT_ATTEMPTS - 1,
            container_created_at=datetime.now(UTC).isoformat(),
        )
        await publisher.publish_next(POOL, ig)
        assert "em dobro" in store.mark_failed.await_args.args[2]

    async def test_token_error_fails_immediately(self, worker_env):
        ig, store = worker_env
        ig.create_container.side_effect = InstagramSendError(401, "expired", code=190)
        store.claim_due.return_value = _pub()
        await publisher.publish_next(POOL, ig)
        assert "Token" in store.mark_failed.await_args.args[2]
        store.postpone.assert_not_awaited()

    async def test_network_error_on_create_postpones(self, worker_env):
        ig, store = worker_env
        ig.create_container.side_effect = TimeoutError("timeout")
        store.claim_due.return_value = _pub()
        await publisher.publish_next(POOL, ig)
        store.postpone.assert_awaited_once()
