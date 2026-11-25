"""Parser do payload de webhook do Instagram para o campo `comments`.

Função pura (sem I/O), como `instagram_payload.py` (que cuida do campo
`messages`). Formato enviado pela Meta quando alguém comenta numa postagem:

    {
      "object": "instagram",
      "entry": [
        {
          "id": "<ID da conta profissional>",
          "time": 1700000000,
          "changes": [
            {
              "field": "comments",
              "value": {
                "id": "<ID do comentário>",
                "text": "Tem no 36?",
                "parent_id": "<ID do comentário pai, só em respostas>",
                "from": {"id": "<IGSID de quem comentou>", "username": "fulana"},
                "media": {"id": "<ID da postagem>", "media_product_type": "FEED"}
              }
            }
          ]
        }
      ]
    }

Comentários feitos pela própria conta (inclusive as respostas publicadas pelo
painel) também chegam aqui: são devolvidos com `is_own=True` para quem chama
decidir (o webhook os grava como `ignored`, sem rascunho).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ParsedInstagramComment:
    """Comentário normalizado a partir do webhook."""

    comment_id: str
    media_id: str
    text: str
    from_id: str | None
    from_username: str | None
    parent_id: str | None
    commented_at: datetime
    is_own: bool


def _timestamp(entry_time: object) -> datetime:
    """Converte `entry.time` (segundos ou milissegundos) para datetime UTC."""
    if isinstance(entry_time, int | float) and entry_time > 0:
        seconds = entry_time / 1000 if entry_time > 10_000_000_000 else entry_time
        return datetime.fromtimestamp(seconds, tz=UTC)
    return datetime.now(UTC)


def parse_instagram_comments(
    payload: dict, *, business_account_id: str = ""
) -> list[ParsedInstagramComment]:
    """Extrai os comentários (campo `comments`) do payload de webhook.

    Args:
        payload: Corpo JSON recebido no webhook.
        business_account_id: ID da conta profissional (settings). Usado junto
            com `entry.id` para marcar comentários da própria conta.

    Returns:
        Lista de comentários (vazia se o payload não traz nenhum).
    """
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []

    parsed: list[ParsedInstagramComment] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue

        own_ids = {str(entry.get("id") or ""), business_account_id} - {""}
        commented_at = _timestamp(entry.get("time"))

        for change in changes:
            if not isinstance(change, dict) or change.get("field") != "comments":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue

            comment_id = value.get("id")
            media = value.get("media")
            media_id = media.get("id") if isinstance(media, dict) else None
            if not comment_id or not media_id:
                continue

            sender = value.get("from")
            from_id = sender.get("id") if isinstance(sender, dict) else None
            from_username = sender.get("username") if isinstance(sender, dict) else None
            text = value.get("text")

            parsed.append(
                ParsedInstagramComment(
                    comment_id=str(comment_id),
                    media_id=str(media_id),
                    text=text if isinstance(text, str) else "",
                    from_id=str(from_id) if from_id else None,
                    from_username=from_username or None,
                    parent_id=str(value["parent_id"])
                    if value.get("parent_id")
                    else None,
                    commented_at=commented_at,
                    is_own=bool(from_id) and str(from_id) in own_ids,
                )
            )

    return parsed
