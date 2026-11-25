"""Geração de legenda (visão + texto) para publicações no Instagram."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from whatsapp_langchain.agents.captions.prompts import (
    CAPTION_SYSTEM,
    DESCRIBE_SYSTEM,
    DESCRIBE_USER,
    build_caption_request,
)
from whatsapp_langchain.shared.llm import create_chat_model
from whatsapp_langchain.shared.publishing import MAX_CAPTION_CHARS, MAX_HASHTAGS
from whatsapp_langchain.worker.instagram_client import to_plain_text
from whatsapp_langchain.worker.media import _chat_completion_media

BRAND_HASHTAG = "#patriciaberberich"
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_VALID_HASHTAG = re.compile(r"^#\w+$", re.UNICODE)


class CaptionParseError(ValueError):
    """A resposta do modelo não é um JSON de legenda válido."""


@dataclass
class CaptionDraft:
    caption: str
    hashtags: list[str]
    notes: str | None

    @property
    def full_text(self) -> str:
        """Legenda + hashtags, pronta para o campo do painel."""
        if not self.hashtags:
            return self.caption
        return f"{self.caption}\n\n{' '.join(self.hashtags)}"


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _normalize_hashtags(raw: object) -> list[str]:
    """Limpa, deduplica (sem diferenciar maiúsculas) e garante a da marca."""
    items = raw if isinstance(raw, list) else str(raw or "").split()
    seen: set[str] = set()
    tags: list[str] = []
    for item in items:
        tag = "#" + str(item).strip().lstrip("#").replace(" ", "")
        if not _VALID_HASHTAG.match(tag) or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
    if BRAND_HASHTAG not in seen:
        tags.insert(0, BRAND_HASHTAG)
    return tags[:MAX_HASHTAGS]


def parse_caption(raw: str) -> CaptionDraft:
    """Interpreta o JSON do modelo e aplica as regras duras da Meta.

    Raises:
        CaptionParseError: Sem JSON válido ou sem legenda.
    """
    match = _JSON_OBJECT.search(raw)
    if not match:
        raise CaptionParseError(f"resposta sem JSON: {raw[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise CaptionParseError(f"JSON inválido: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise CaptionParseError("JSON não é um objeto")

    caption = to_plain_text(str(data.get("caption") or ""))
    if not caption:
        raise CaptionParseError("legenda vazia")

    # Hashtags que o modelo colocou no corpo da legenda vão para a lista.
    inline = re.findall(r"(?<!\w)#\w+", caption, re.UNICODE)
    if inline:
        caption = re.sub(r"(?<!\w)#\w+", "", caption, flags=re.UNICODE)
        caption = re.sub(r"[ \t]+\n", "\n", caption).strip()
    hashtags = _normalize_hashtags(list(data.get("hashtags") or []) + inline)

    draft = CaptionDraft(caption=caption, hashtags=hashtags, notes=None)
    while len(draft.full_text) > MAX_CAPTION_CHARS and draft.hashtags:
        draft.hashtags.pop()
    if len(draft.full_text) > MAX_CAPTION_CHARS:
        draft.caption = draft.caption[:MAX_CAPTION_CHARS].rsplit(" ", 1)[0]

    notes = data.get("notes")
    draft.notes = notes.strip() if isinstance(notes, str) and notes.strip() else None
    return draft


async def describe_image(image_bytes: bytes, content_type: str = "image/jpeg") -> str:
    """Descreve a foto (produto) com o modelo de visão."""
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    return await _chat_completion_media(
        [
            {"role": "system", "content": DESCRIBE_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": DESCRIBE_USER},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{image_b64}"},
                    },
                ],
            },
        ]
    )


async def generate_caption(
    *,
    kind: str,
    brief: str,
    media_descriptions: list[str],
    media_count: int,
    has_video: bool,
) -> CaptionDraft:
    """Escreve a legenda com o modelo principal."""
    model = create_chat_model(temperature=0.7)
    response = await model.ainvoke(
        [
            SystemMessage(content=CAPTION_SYSTEM),
            HumanMessage(
                content=build_caption_request(
                    kind=kind,
                    brief=brief,
                    media_descriptions=media_descriptions,
                    media_count=media_count,
                    has_video=has_video,
                )
            ),
        ]
    )
    return parse_caption(_content_text(response.content))
