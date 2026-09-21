"""Parser do payload de webhook do Evolution API (evento messages.upsert).

Função pura (sem I/O) — facilita testes unitários sem subir a API.

Formato esperado (Evolution API v2, evento `messages.upsert`, instância com
`webhookBase64=true`):

    {
      "event": "messages.upsert",
      "instance": "minha-instancia",
      "data": {
        "key": {
          "remoteJid": "5511999999999@s.whatsapp.net",
          "fromMe": false,
          "id": "..."
        },
        "message": {"conversation": "Olá"},
        "messageType": "conversation"
      }
    }

Se o formato da sua instância divergir um pouco (varia entre versões
menores do Evolution), ajuste a extração aqui — é o único lugar que
interpreta o payload.
"""

from __future__ import annotations

from dataclasses import dataclass

MESSAGE_EVENTS = {"messages.upsert", "MESSAGES_UPSERT"}

# Tipos de mídia que o pipeline sabe processar (ver worker/media.py).
SUPPORTED_MEDIA_TYPES = ("imageMessage", "audioMessage")


@dataclass
class ParsedEvolutionMessage:
    """Mensagem inbound normalizada a partir do payload do Evolution."""

    phone_number: str
    message_id: str
    body: str
    media_base64: str | None
    media_type: str | None


def parse_evolution_message(payload: dict) -> ParsedEvolutionMessage | None:
    """Extrai uma mensagem inbound do payload de webhook, ou None se ignorável.

    Ignora: eventos que não são de mensagem, mensagens enviadas pelo próprio
    bot (fromMe=true, evita eco/loop) e mensagens de grupo (remoteJid
    terminado em "@g.us").

    Args:
        payload: Corpo JSON recebido no webhook.

    Returns:
        ParsedEvolutionMessage normalizada, ou None se o evento deve ser
        descartado sem enfileirar nada.
    """
    if not isinstance(payload, dict):
        return None

    if payload.get("event") not in MESSAGE_EVENTS:
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    key = data.get("key")
    if not isinstance(key, dict):
        return None

    if key.get("fromMe"):
        return None

    remote_jid = key.get("remoteJid") or ""
    if not remote_jid or remote_jid.endswith("@g.us"):
        return None

    phone_number = "+" + remote_jid.split("@")[0]
    message_id = key.get("id") or ""

    message_obj = data.get("message")
    if not isinstance(message_obj, dict):
        return None

    message_type = data.get("messageType") or ""

    if message_type in ("conversation", "extendedTextMessage"):
        text = message_obj.get("conversation") or ""
        if not text:
            ext = message_obj.get("extendedTextMessage")
            if isinstance(ext, dict):
                text = ext.get("text") or ""
        return ParsedEvolutionMessage(
            phone_number=phone_number,
            message_id=message_id,
            body=text,
            media_base64=None,
            media_type=None,
        )

    if message_type in SUPPORTED_MEDIA_TYPES:
        media_obj = message_obj.get(message_type)
        media_obj = media_obj if isinstance(media_obj, dict) else {}
        return ParsedEvolutionMessage(
            phone_number=phone_number,
            message_id=message_id,
            body=media_obj.get("caption") or "",
            media_base64=message_obj.get("base64"),
            media_type=media_obj.get("mimetype") or "",
        )

    if message_type:
        # Tipo reconhecido pelo Evolution mas sem suporte de processamento
        # (vídeo, documento, sticker, localização, contato...). Sinaliza
        # como mídia "não suportada" para o worker responder
        # automaticamente em vez de invocar o agente com texto vazio.
        return ParsedEvolutionMessage(
            phone_number=phone_number,
            message_id=message_id,
            body="",
            media_base64=None,
            media_type=f"unsupported/{message_type}",
        )

    return None
