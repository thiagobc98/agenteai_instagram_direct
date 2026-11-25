"""Interpreta o webhook `feed` da Página do Facebook (comentários dos posts).

Formato (objeto "page", campo "feed"):

    {"object": "page", "entry": [{"id": "<PAGE_ID>", "time": 1700000000,
      "changes": [{"field": "feed", "value": {
          "item": "comment", "verb": "add",
          "comment_id": "<POST>_<COMMENT>", "post_id": "<PAGE>_<POST>",
          "parent_id": "<PAGE>_<POST>",          # = post_id no comentário raiz
          "from": {"id": "<PSID>", "name": "Vanessa Quites"},
          "message": "Você brilhou!", "created_time": 1700000000}}]}]}

Só interessa `item == "comment"`. Curtidas, reações e posts novos chegam no
mesmo campo e são ignorados. O texto do comentário é dado de terceiros:
quem usa (IA) trata como dado, nunca como instrução.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# Teto defensivo: um evento com texto gigante não deve ir inteiro para o banco
# nem para o modelo (o Facebook aceita até 8000 caracteres por comentário).
MAX_COMMENT_TEXT = 8000

VERB_ADD = "add"
VERB_EDITED = "edited"
VERB_REMOVE = "remove"
_KNOWN_VERBS = {VERB_ADD, VERB_EDITED, VERB_REMOVE}


@dataclass(frozen=True)
class ParsedFacebookComment:
    comment_id: str
    post_id: str
    # None quando é comentário direto no post (parent_id == post_id)
    parent_id: str | None
    from_id: str | None
    from_name: str | None
    text: str
    commented_at: datetime
    verb: str
    # Comentário da própria Página (inclusive as respostas do painel)
    is_own: bool


def _time(value: object) -> datetime:
    """`created_time` vem em segundos Unix (às vezes ISO 8601)."""
    if isinstance(value, int | float) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("+0000", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def parse_facebook_comments(
    payload: object, page_id: str
) -> list[ParsedFacebookComment]:
    """Extrai os eventos de comentário do webhook da Página.

    Args:
        payload: JSON do webhook (já com a assinatura validada).
        page_id: ID da Página configurada. Entradas de outras Páginas são
            descartadas: o app pode estar inscrito em mais de uma, e esta
            integração só responde pela Página da loja.
    """
    if not isinstance(payload, dict) or payload.get("object") != "page":
        return []

    parsed: list[ParsedFacebookComment] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict) or str(entry.get("id") or "") != page_id:
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") != "feed":
                continue
            value = change.get("value")
            if not isinstance(value, dict) or value.get("item") != "comment":
                continue
            verb = str(value.get("verb") or "")
            comment_id = str(value.get("comment_id") or "")
            post_id = str(value.get("post_id") or "")
            if verb not in _KNOWN_VERBS or not comment_id or not post_id:
                continue

            sender = value.get("from") if isinstance(value.get("from"), dict) else {}
            from_id = str(sender.get("id") or "") or None
            parent = str(value.get("parent_id") or "")
            parsed.append(
                ParsedFacebookComment(
                    comment_id=comment_id,
                    post_id=post_id,
                    parent_id=parent if parent and parent != post_id else None,
                    from_id=from_id,
                    from_name=(str(sender.get("name") or "").strip() or None),
                    text=str(value.get("message") or "")[:MAX_COMMENT_TEXT],
                    commented_at=_time(value.get("created_time")),
                    verb=verb,
                    is_own=from_id is not None and from_id == page_id,
                )
            )
    return parsed
