"""Agente de legendas para publicações no Instagram (Feed e Reels).

Duas etapas:
1. `describe_image`: o modelo de visão (OPENROUTER_MIDIA_MODEL) descreve cada
   foto, focado no produto. A descrição fica salva por mídia (cache).
2. `generate_caption`: o modelo principal escreve legenda + hashtags a partir
   do briefing da equipe e das descrições.

Separar as etapas deixa o modelo principal livre (não precisa ter visão) e
evita pagar a análise da mesma foto a cada "gerar de novo".
"""

from whatsapp_langchain.agents.captions.generator import (
    CaptionDraft,
    CaptionParseError,
    describe_image,
    generate_caption,
    parse_caption,
)

__all__ = [
    "CaptionDraft",
    "CaptionParseError",
    "describe_image",
    "generate_caption",
    "parse_caption",
]
