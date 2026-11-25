"""Geração do rascunho de resposta a um comentário (uma chamada ao modelo)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from whatsapp_langchain.agents.comments.prompts import SYSTEM_PROMPT, build_user_message
from whatsapp_langchain.agents.middleware.handoff_context import expand_patricia_link
from whatsapp_langchain.shared.llm import create_chat_model
from whatsapp_langchain.worker.instagram_client import (
    MAX_COMMENT_CHARS,
    MAX_MESSAGE_BYTES,
    split_message,
)


class DraftParseError(ValueError):
    """A resposta do modelo não é um JSON de rascunho válido."""


@dataclass
class CommentDraft:
    public: str
    private: str
    ignore: bool
    reason: str | None


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _content_text(content: object) -> str:
    """Extrai o texto da resposta do modelo (string ou lista de blocos)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def parse_draft(raw: str) -> CommentDraft:
    """Interpreta o JSON devolvido pelo modelo.

    Tolera texto ou cerca de código ao redor do objeto JSON.

    Raises:
        DraftParseError: Se não houver um objeto JSON válido.
    """
    match = _JSON_OBJECT.search(raw)
    if not match:
        raise DraftParseError(f"resposta sem JSON: {raw[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise DraftParseError(f"JSON inválido: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise DraftParseError("JSON não é um objeto")

    def text(key: str) -> str:
        value = data.get(key)
        return value.strip() if isinstance(value, str) else ""

    ignore = bool(data.get("ignore"))
    public = text("public")
    if not public and not ignore:
        raise DraftParseError("rascunho sem resposta pública")

    # Rede de segurança: o painel bloqueia acima dos limites do Instagram,
    # mas um rascunho fora do limite não deve nem chegar lá.
    if len(public) > MAX_COMMENT_CHARS:
        public = public[:MAX_COMMENT_CHARS].rsplit(" ", 1)[0]
    # Link da Patrícia sai sempre completo, mesmo se o modelo errou a cópia
    private = expand_patricia_link(text("private"))
    if len(private.encode("utf-8")) > MAX_MESSAGE_BYTES:
        private = split_message(private, MAX_MESSAGE_BYTES)[0]

    return CommentDraft(
        public=public,
        private=private,
        ignore=ignore,
        reason=text("reason") or None,
    )


async def generate_draft(
    *,
    comment_text: str,
    from_username: str | None,
    post_caption: str | None,
    is_reply: bool = False,
) -> CommentDraft:
    """Pede ao modelo o rascunho de resposta pública + privada."""
    model = create_chat_model(temperature=0.4)
    response = await model.ainvoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=build_user_message(
                    comment_text=comment_text,
                    from_username=from_username,
                    post_caption=post_caption,
                    is_reply=is_reply,
                )
            ),
        ]
    )
    return parse_draft(_content_text(response.content))
