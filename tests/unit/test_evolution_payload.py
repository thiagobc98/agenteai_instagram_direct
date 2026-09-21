"""Testes do parser de payload de webhook do Evolution API."""

from whatsapp_langchain.shared.evolution_payload import parse_evolution_message


def _base_payload(**data_overrides) -> dict:
    data = {
        "key": {
            "remoteJid": "5511999999999@s.whatsapp.net",
            "fromMe": False,
            "id": "MSG123",
        },
        "message": {"conversation": "Olá"},
        "messageType": "conversation",
    }
    data.update(data_overrides)
    return {"event": "messages.upsert", "instance": "test", "data": data}


class TestIgnoredEvents:
    """Eventos que devem ser descartados sem enfileirar nada."""

    def test_ignores_non_message_event(self):
        payload = {"event": "connection.update", "data": {}}
        assert parse_evolution_message(payload) is None

    def test_ignores_missing_event(self):
        assert parse_evolution_message({"data": {}}) is None

    def test_ignores_from_me(self):
        payload = _base_payload(
            key={
                "remoteJid": "5511999999999@s.whatsapp.net",
                "fromMe": True,
                "id": "MSG123",
            }
        )
        assert parse_evolution_message(payload) is None

    def test_ignores_group_messages(self):
        payload = _base_payload(
            key={
                "remoteJid": "120363000000000000@g.us",
                "fromMe": False,
                "id": "MSG123",
            }
        )
        assert parse_evolution_message(payload) is None

    def test_ignores_missing_remote_jid(self):
        payload = _base_payload(key={"fromMe": False, "id": "MSG123"})
        assert parse_evolution_message(payload) is None

    def test_ignores_non_dict_payload(self):
        assert parse_evolution_message("not-a-dict") is None  # type: ignore[arg-type]

    def test_ignores_missing_data(self):
        assert parse_evolution_message({"event": "messages.upsert"}) is None

    def test_ignores_missing_message_object(self):
        payload = _base_payload()
        del payload["data"]["message"]
        assert parse_evolution_message(payload) is None

    def test_ignores_unrecognized_message_type_without_type(self):
        payload = _base_payload(messageType="", message={})
        assert parse_evolution_message(payload) is None

    def test_accepts_uppercase_event_variant(self):
        payload = _base_payload()
        payload["event"] = "MESSAGES_UPSERT"
        result = parse_evolution_message(payload)
        assert result is not None


class TestTextMessages:
    """Extração de texto (conversation / extendedTextMessage)."""

    def test_parses_plain_text(self):
        result = parse_evolution_message(_base_payload())
        assert result is not None
        assert result.phone_number == "+5511999999999"
        assert result.message_id == "MSG123"
        assert result.body == "Olá"
        assert result.media_base64 is None
        assert result.media_type is None

    def test_parses_extended_text_message(self):
        payload = _base_payload(
            message={"extendedTextMessage": {"text": "Resposta citada"}},
            messageType="extendedTextMessage",
        )
        result = parse_evolution_message(payload)
        assert result is not None
        assert result.body == "Resposta citada"


class TestMediaMessages:
    """Extração de mídia (imagem/áudio) com base64."""

    def test_parses_image_message(self):
        payload = _base_payload(
            message={
                "imageMessage": {
                    "mimetype": "image/jpeg",
                    "caption": "Veja isso",
                },
                "base64": "aGVsbG8=",
            },
            messageType="imageMessage",
        )
        result = parse_evolution_message(payload)
        assert result is not None
        assert result.body == "Veja isso"
        assert result.media_base64 == "aGVsbG8="
        assert result.media_type == "image/jpeg"

    def test_parses_audio_message_without_caption(self):
        payload = _base_payload(
            message={
                "audioMessage": {"mimetype": "audio/ogg; codecs=opus"},
                "base64": "YXVkaW8=",
            },
            messageType="audioMessage",
        )
        result = parse_evolution_message(payload)
        assert result is not None
        assert result.body == ""
        assert result.media_base64 == "YXVkaW8="
        assert result.media_type == "audio/ogg; codecs=opus"

    def test_unsupported_media_type_flags_as_unsupported(self):
        payload = _base_payload(
            message={"videoMessage": {"mimetype": "video/mp4"}},
            messageType="videoMessage",
        )
        result = parse_evolution_message(payload)
        assert result is not None
        assert result.media_base64 is None
        assert result.media_type == "unsupported/videoMessage"
        assert result.body == ""


class TestPhoneNumberExtraction:
    """Normalização do remoteJid para telefone E.164."""

    def test_adds_plus_prefix(self):
        result = parse_evolution_message(_base_payload())
        assert result is not None
        assert result.phone_number.startswith("+")

    def test_strips_whatsapp_suffix(self):
        payload = _base_payload(
            key={
                "remoteJid": "5521988887777@s.whatsapp.net",
                "fromMe": False,
                "id": "X",
            }
        )
        result = parse_evolution_message(payload)
        assert result is not None
        assert result.phone_number == "+5521988887777"
