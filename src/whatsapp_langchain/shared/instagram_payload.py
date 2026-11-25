"""Parser do payload de webhook da Instagram Messaging API (campo `messages`).

Função pura (sem I/O) — facilita testes unitários sem subir a API.

Formato esperado (POST da Meta para o webhook, campo `messages`):

    {
      "object": "instagram",
      "entry": [
        {
          "id": "<ID da conta profissional>",
          "time": 1700000000000,
          "messaging": [
            {
              "sender": {"id": "<IGSID do cliente>"},
              "recipient": {"id": "<ID da conta profissional>"},
              "timestamp": 1700000000000,
              "message": {
                "mid": "<id da mensagem>",
                "text": "Olá",
                "attachments": [
                  {"type": "image", "payload": {"url": "https://..."}}
                ]
              }
            }
          ]
        }
      ]
    }

O botão "Testar" do painel da Meta envia o mesmo evento no formato
`entry[].changes[].value` — também aceito aqui.

Um único POST pode trazer vários eventos (batch), por isso o parser devolve
uma lista. Se o formato divergir um pouco (a Meta muda campos com frequência),
ajuste a extração aqui — é o único lugar que interpreta o payload.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tipos de attachment que o pipeline sabe processar (ver worker/media.py).
# O valor é o MIME "genérico" gravado na fila; o MIME real vem do
# Content-Type do download da URL.
SUPPORTED_ATTACHMENT_TYPES = {
    "image": "image/*",
    "audio": "audio/*",
}

# Attachments sem conteúdo útil para o atendimento (curtir a mensagem com
# o coração): descartados sem resposta automática.
IGNORED_ATTACHMENT_TYPES = {"like_heart"}


@dataclass
class ParsedInstagramMessage:
    """Mensagem inbound normalizada a partir do payload do Instagram."""

    external_id: str  # IGSID do remetente
    message_id: str
    body: str
    media_url: str | None
    media_type: str | None


def _events(payload: dict) -> list[dict]:
    """Extrai a lista plana de eventos de mensagem de todas as entries."""
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []

    events: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        messaging = entry.get("messaging")
        if isinstance(messaging, list):
            events.extend(e for e in messaging if isinstance(e, dict))

        changes = entry.get("changes")
        if isinstance(changes, list):
            for change in changes:
                if not isinstance(change, dict):
                    continue
                if change.get("field") not in (None, "messages"):
                    continue
                value = change.get("value")
                if isinstance(value, dict):
                    events.append(value)

    return events


def _parse_attachment(attachments: object) -> tuple[str | None, str | None]:
    """Interpreta o primeiro attachment.

    Returns:
        (media_url, media_type) — ambos None quando não há attachment ou ele
        é descartável (ex: like_heart).
    """
    if not isinstance(attachments, list):
        return None, None

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue

        kind = attachment.get("type") or ""
        if kind in IGNORED_ATTACHMENT_TYPES:
            return None, None

        payload = attachment.get("payload")
        url = payload.get("url") if isinstance(payload, dict) else None

        if kind in SUPPORTED_ATTACHMENT_TYPES and url:
            return url, SUPPORTED_ATTACHMENT_TYPES[kind]

        # Tipo conhecido pelo Instagram mas sem suporte de processamento
        # (vídeo, arquivo, share, reel, story_mention...). Sinaliza como
        # mídia "não suportada" para o worker responder automaticamente em
        # vez de invocar o agente com texto vazio.
        return None, f"unsupported/{kind or 'unknown'}"

    return None, None


def parse_instagram_messages(payload: dict) -> list[ParsedInstagramMessage]:
    """Extrai as mensagens inbound do payload de webhook.

    Ignora: eventos que não são mensagem (read receipts, reações, postbacks),
    ecos de mensagens enviadas pela própria conta (`is_echo`, evita loop),
    mensagens da própria conta (`is_self`), mensagens apagadas (`is_deleted`)
    e eventos sem conteúdo. Mensagens de mídia múltipla: só o primeiro
    attachment é processado.

    Args:
        payload: Corpo JSON recebido no webhook.

    Returns:
        Lista de mensagens normalizadas (vazia se nada deve ser enfileirado).
    """
    if not isinstance(payload, dict):
        return []

    parsed: list[ParsedInstagramMessage] = []

    for event in _events(payload):
        message = event.get("message")
        if not isinstance(message, dict):
            continue

        if message.get("is_echo") or message.get("is_self"):
            continue
        if message.get("is_deleted"):
            continue

        sender = event.get("sender")
        external_id = sender.get("id") if isinstance(sender, dict) else None
        if not external_id:
            continue

        message_id = message.get("mid") or ""
        text = message.get("text")
        body = text if isinstance(text, str) else ""

        media_url, media_type = _parse_attachment(message.get("attachments"))

        if message.get("is_unsupported") and not media_type:
            media_type = "unsupported/unknown"

        if not body and not media_type:
            # Nada aproveitável (só like_heart, ou evento vazio).
            continue

        parsed.append(
            ParsedInstagramMessage(
                external_id=str(external_id),
                message_id=message_id,
                body=body,
                media_url=media_url,
                media_type=media_type,
            )
        )

    return parsed
