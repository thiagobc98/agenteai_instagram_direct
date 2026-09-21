"""Testes do parser de payload de webhook do Instagram Messaging API."""

from whatsapp_langchain.shared.instagram_payload import parse_instagram_messages

SENDER = "17841400000000001"
BUSINESS = "17841400000000000"


def _event(message: dict | None = None, **overrides) -> dict:
    event = {
        "sender": {"id": SENDER},
        "recipient": {"id": BUSINESS},
        "timestamp": 1700000000000,
        "message": {"mid": "MID123", "text": "Olá"} if message is None else message,
    }
    event.update(overrides)
    return event


def _payload(*events: dict) -> dict:
    return {
        "object": "instagram",
        "entry": [{"id": BUSINESS, "time": 1700000000000, "messaging": list(events)}],
    }


class TestTextMessages:
    def test_parses_text_message(self):
        [msg] = parse_instagram_messages(_payload(_event()))
        assert msg.external_id == SENDER
        assert msg.message_id == "MID123"
        assert msg.body == "Olá"
        assert msg.media_url is None
        assert msg.media_type is None

    def test_parses_batch_of_messages(self):
        payload = _payload(
            _event({"mid": "A", "text": "um"}),
            _event({"mid": "B", "text": "dois"}, sender={"id": "999"}),
        )
        messages = parse_instagram_messages(payload)
        assert [m.message_id for m in messages] == ["A", "B"]
        assert [m.external_id for m in messages] == [SENDER, "999"]

    def test_parses_multiple_entries(self):
        payload = {
            "object": "instagram",
            "entry": [
                {"id": BUSINESS, "messaging": [_event({"mid": "A", "text": "um"})]},
                {"id": BUSINESS, "messaging": [_event({"mid": "B", "text": "dois"})]},
            ],
        }
        assert len(parse_instagram_messages(payload)) == 2

    def test_parses_changes_format_from_dashboard_test_button(self):
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": BUSINESS,
                    "changes": [{"field": "messages", "value": _event()}],
                }
            ],
        }
        [msg] = parse_instagram_messages(payload)
        assert msg.body == "Olá"

    def test_ignores_changes_of_other_fields(self):
        payload = {
            "object": "instagram",
            "entry": [
                {"id": BUSINESS, "changes": [{"field": "comments", "value": {}}]}
            ],
        }
        assert parse_instagram_messages(payload) == []


class TestIgnoredEvents:
    """Eventos que devem ser descartados sem enfileirar nada."""

    def test_ignores_echo(self):
        payload = _payload(_event({"mid": "M", "text": "resposta", "is_echo": True}))
        assert parse_instagram_messages(payload) == []

    def test_ignores_is_self(self):
        payload = _payload(_event({"mid": "M", "text": "eu", "is_self": True}))
        assert parse_instagram_messages(payload) == []

    def test_ignores_deleted_message(self):
        payload = _payload(_event({"mid": "M", "is_deleted": True}))
        assert parse_instagram_messages(payload) == []

    def test_ignores_read_receipt(self):
        event = {
            "sender": {"id": SENDER},
            "recipient": {"id": BUSINESS},
            "timestamp": 1700000000000,
            "read": {"mid": "MID123"},
        }
        assert parse_instagram_messages(_payload(event)) == []

    def test_ignores_reaction(self):
        event = {
            "sender": {"id": SENDER},
            "recipient": {"id": BUSINESS},
            "reaction": {"mid": "MID123", "action": "react", "reaction": "love"},
        }
        assert parse_instagram_messages(_payload(event)) == []

    def test_ignores_like_heart_sticker(self):
        message = {
            "mid": "M",
            "attachments": [{"type": "like_heart", "payload": {"url": "https://x"}}],
        }
        assert parse_instagram_messages(_payload(_event(message))) == []

    def test_ignores_missing_sender(self):
        event = {"recipient": {"id": BUSINESS}, "message": {"mid": "M", "text": "oi"}}
        assert parse_instagram_messages(_payload(event)) == []

    def test_ignores_empty_message(self):
        assert parse_instagram_messages(_payload(_event({"mid": "M"}))) == []


class TestMalformedPayloads:
    def test_non_dict_payload(self):
        assert parse_instagram_messages("not-a-dict") == []  # type: ignore[arg-type]

    def test_missing_entry(self):
        assert parse_instagram_messages({"object": "instagram"}) == []

    def test_entry_not_a_list(self):
        assert parse_instagram_messages({"entry": "x"}) == []

    def test_entry_with_garbage(self):
        assert parse_instagram_messages({"entry": ["x", 1, None]}) == []

    def test_messaging_not_a_list(self):
        assert parse_instagram_messages({"entry": [{"messaging": "x"}]}) == []

    def test_message_not_a_dict(self):
        payload = _payload(_event("texto solto"))  # type: ignore[arg-type]
        assert parse_instagram_messages(payload) == []

    def test_text_not_a_string_is_treated_as_empty(self):
        assert parse_instagram_messages(_payload(_event({"mid": "M", "text": 5}))) == []

    def test_sender_not_a_dict(self):
        assert parse_instagram_messages(_payload(_event(sender="x"))) == []


class TestAttachments:
    def test_parses_image_attachment(self):
        message = {
            "mid": "M",
            "attachments": [
                {"type": "image", "payload": {"url": "https://cdn.example/img.jpg"}}
            ],
        }
        [msg] = parse_instagram_messages(_payload(_event(message)))
        assert msg.media_url == "https://cdn.example/img.jpg"
        assert msg.media_type == "image/*"
        assert msg.body == ""

    def test_parses_audio_attachment(self):
        message = {
            "mid": "M",
            "attachments": [
                {"type": "audio", "payload": {"url": "https://cdn.example/a.mp4"}}
            ],
        }
        [msg] = parse_instagram_messages(_payload(_event(message)))
        assert msg.media_url == "https://cdn.example/a.mp4"
        assert msg.media_type == "audio/*"

    def test_keeps_text_alongside_attachment(self):
        message = {
            "mid": "M",
            "text": "veja isso",
            "attachments": [
                {"type": "image", "payload": {"url": "https://cdn.example/i.jpg"}}
            ],
        }
        [msg] = parse_instagram_messages(_payload(_event(message)))
        assert msg.body == "veja isso"
        assert msg.media_url == "https://cdn.example/i.jpg"

    def test_only_first_attachment_is_used(self):
        message = {
            "mid": "M",
            "attachments": [
                {"type": "image", "payload": {"url": "https://cdn.example/1.jpg"}},
                {"type": "image", "payload": {"url": "https://cdn.example/2.jpg"}},
            ],
        }
        [msg] = parse_instagram_messages(_payload(_event(message)))
        assert msg.media_url == "https://cdn.example/1.jpg"

    def test_marks_unsupported_attachment_types(self):
        for kind in ("video", "file", "share", "ig_reel", "story_mention"):
            message = {
                "mid": "M",
                "attachments": [{"type": kind, "payload": {"url": "https://x/y"}}],
            }
            [msg] = parse_instagram_messages(_payload(_event(message)))
            assert msg.media_type == f"unsupported/{kind}"
            assert msg.media_url is None

    def test_image_without_url_is_unsupported(self):
        message = {"mid": "M", "attachments": [{"type": "image", "payload": {}}]}
        [msg] = parse_instagram_messages(_payload(_event(message)))
        assert msg.media_type == "unsupported/image"

    def test_is_unsupported_flag(self):
        [msg] = parse_instagram_messages(
            _payload(_event({"mid": "M", "is_unsupported": True}))
        )
        assert msg.media_type == "unsupported/unknown"
        assert msg.body == ""

    def test_attachments_not_a_list(self):
        message = {"mid": "M", "text": "oi", "attachments": "x"}
        [msg] = parse_instagram_messages(_payload(_event(message)))
        assert msg.body == "oi"
        assert msg.media_type is None
