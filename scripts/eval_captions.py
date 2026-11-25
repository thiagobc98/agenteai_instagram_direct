"""Avalia as legendas do agente de publicações contra as regras de negócio.

Usa descrições de imagem fixas (sem chamar o modelo de visão), para isolar a
etapa de escrita da legenda. Confere de forma determinística o que NÃO pode
sair numa publicação da marca: preço ou desconto inventado, numeração fora
do 34-39, markdown, hashtag de engajamento genérica, falta da chamada para o
Direct etc.

Chama o modelo de verdade (gasta créditos do OpenRouter): 1 chamada por caso.

Uso:
    uv run --extra dev python scripts/eval_captions.py
    uv run --extra dev python scripts/eval_captions.py --repeat 3 --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from whatsapp_langchain.agents.captions import CaptionDraft, generate_caption

SCARPIN = (
    "Scarpin de couro liso na cor nude, bico fino, salto agulha de cerca de 7 cm. "
    "Foto de estúdio com fundo bege claro."
)
SANDALIA = (
    "Sandália de tiras finas douradas, salto bloco de uns 5 cm, fivela no tornozelo. "
    "Look completo com vestido branco, ambiente externo."
)

_PRICE = re.compile(r"R\$\s*\d|\d+\s*reais|\bpix\b", re.IGNORECASE)
_DISCOUNT = re.compile(r"\d+\s*%|\bdesconto\b|\bpromo", re.IGNORECASE)
_SIZE = re.compile(r"\b(3[0-3]|4[0-9])\b")
_GENERIC_TAGS = {"#follow", "#like4like", "#instagood", "#followme", "#l4l", "#f4f"}

Check = Callable[[CaptionDraft], str | None]


def no_price(d: CaptionDraft) -> str | None:
    return "inventou preço" if _PRICE.search(d.caption) else None


def no_discount(d: CaptionDraft) -> str | None:
    return "inventou desconto/promoção" if _DISCOUNT.search(d.caption) else None


def mentions_discount(d: CaptionDraft) -> str | None:
    return None if "20%" in d.caption else "não usou o desconto do briefing"


def no_invented_size(d: CaptionDraft) -> str | None:
    return "numeração fora do 34-39" if _SIZE.search(d.caption) else None


def no_markdown(d: CaptionDraft) -> str | None:
    return "markdown" if re.search(r"\*\*|__|^#\s", d.caption, re.M) else None


def brand_tag(d: CaptionDraft) -> str | None:
    return None if "#patriciaberberich" in d.hashtags else "sem #patriciaberberich"


def tag_count(d: CaptionDraft) -> str | None:
    n = len(d.hashtags)
    return None if 5 <= n <= 13 else f"{n} hashtags (esperado 5 a 12 + marca)"


def no_generic_tags(d: CaptionDraft) -> str | None:
    bad = {t.lower() for t in d.hashtags} & _GENERIC_TAGS
    return f"hashtag genérica: {', '.join(sorted(bad))}" if bad else None


def has_cta(d: CaptionDraft) -> str | None:
    return (
        None
        if re.search(r"direct|dm", d.caption, re.I)
        else "sem chamada para o Direct"
    )


def hook_fits(d: CaptionDraft) -> str | None:
    first = d.caption.split("\n", 1)[0]
    return (
        None if len(first) <= 125 else f"primeira linha longa ({len(first)} caracteres)"
    )


def swipe_hint(d: CaptionDraft) -> str | None:
    return (
        None
        if re.search(r"arrast|deslize|passa pro lado", d.caption, re.I)
        else ("carrossel sem convite para arrastar")
    )


BASE: list[Check] = [
    no_price,
    no_invented_size,
    no_markdown,
    brand_tag,
    tag_count,
    no_generic_tags,
    has_cta,
    hook_fits,
]


@dataclass
class Case:
    name: str
    kind: str
    brief: str
    descriptions: list[str]
    checks: list[Check] = field(default_factory=list)
    has_video: bool = False


CASES = [
    Case(
        "lancamento", "feed", "Lançamento do scarpin Bianca", [SCARPIN], [no_discount]
    ),
    Case("sem_briefing", "feed", "", [SCARPIN], [no_discount]),
    Case(
        "carrossel",
        "feed",
        "Novidades da semana",
        [SCARPIN, SANDALIA],
        [no_discount, swipe_hint],
    ),
    Case(
        "promo_do_briefing",
        "feed",
        "Sandália dourada com 20% de desconto só neste fim de semana",
        [SANDALIA],
        [mentions_discount],
    ),
    Case(
        "reels_sem_descricao",
        "reels",
        "Reels mostrando o scarpin nude no pé, andando na rua",
        [],
        [no_discount],
        has_video=True,
    ),
    Case(
        "briefing_pede_preco",
        "feed",
        "Fala que o scarpin está saindo muito",
        [SCARPIN],
        [no_discount],
    ),
]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    total = passed = 0
    for case in [c for c in CASES if not args.only or args.only in c.name]:
        for i in range(args.repeat):
            try:
                draft = await generate_caption(
                    kind=case.kind,
                    brief=case.brief,
                    media_descriptions=case.descriptions,
                    media_count=max(len(case.descriptions), 1),
                    has_video=case.has_video,
                )
                failures = [m for c in BASE + case.checks if (m := c(draft))]
            except Exception as exc:
                draft, failures = None, [f"erro: {exc}"]
            total += 1
            passed += not failures
            suffix = f" #{i + 1}" if args.repeat > 1 else ""
            tag = "OK   " if not failures else "FALHA"
            print(f"{tag} {case.name}{suffix}: {'; '.join(failures)}")
            if args.verbose and draft:
                print("      " + draft.full_text.replace("\n", "\n      "))
                if draft.notes:
                    print(f"      notas: {draft.notes}")

    print(f"\n{passed}/{total} casos sem violação ({passed / max(total, 1):.0%})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
