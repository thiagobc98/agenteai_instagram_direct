"""Avalia o encaminhamento à Patrícia no Direct, com o modelo de verdade.

Roda o agente do Direct (secretaria) em conversas fixas, sem Instagram e sem
banco (o salvamento do WhatsApp é simulado), e confere se:
- valor, número específico, cores e frete: pede o WhatsApp da cliente E manda
  o link da Patrícia na mesma mensagem, sem inventar preço;
- perguntas que a Juliana resolve sozinha (endereço, faixa de numeração) não
  viram encaminhamento;
- quando a cliente manda o WhatsApp, a tool salva o número e não pede de novo;
- cliente que veio de um comentário: continua o assunto, sem se apresentar
  de novo, e salva o número.

Chama o modelo de verdade (gasta créditos do OpenRouter). Use antes de mexer
no prompt da secretaria ou trocar OPENROUTER_MODEL.

Uso:
    uv run --extra dev python scripts/eval_direct_handoff.py
    uv run --extra dev python scripts/eval_direct_handoff.py --only comentario --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from whatsapp_langchain.agents.catalog.secretaria.agent import build_graph
from whatsapp_langchain.agents.middleware.handoff_context import (
    PATRICIA_LINK,
    expand_patricia_link,
)
from whatsapp_langchain.worker.instagram_client import split_bubbles

HANDOFF = "wa.me/5531993456562"
_PRICE = re.compile(r"R\$\s*\d|\d+\s*reais|\d+,\d{2}\b", re.I)
# Pedido de número ("me passa seu WhatsApp", "qual seu zap?", "com DDD"), não
# só citar ("ela vai te chamar no seu WhatsApp")
_ASKS_WHATSAPP = re.compile(
    r"(me (passa|manda|informa|envia)|pode (me )?(passar|mandar|informar)"
    r"|qual (é )?(o )?seu)[^.?!\n]{0,40}(whats\s*app|zap|n[uú]mero)|\bddd\b",
    re.I,
)


@dataclass
class Run:
    replies: list[str]
    saved: list[str]


Check = Callable[[Run], str | None]


def last(r: Run) -> str:
    return r.replies[-1]


def sends_link(r: Run) -> str | None:
    return None if HANDOFF in last(r) else "não mandou o link da Patrícia"


def asks_whatsapp(r: Run) -> str | None:
    return None if _ASKS_WHATSAPP.search(last(r)) else "não pediu o WhatsApp"


def does_not_ask_whatsapp(r: Run) -> str | None:
    return "pediu o WhatsApp de novo" if _ASKS_WHATSAPP.search(last(r)) else None


def no_link(r: Run) -> str | None:
    return "encaminhou sem precisar" if HANDOFF in last(r) else None


def no_price(r: Run) -> str | None:
    return "citou preço" if any(_PRICE.search(x) for x in r.replies) else None


def no_markdown_link(r: Run) -> str | None:
    return "link em markdown" if re.search(r"\]\(", " ".join(r.replies)) else None


def saved(number: str) -> Check:
    def check(r: Run) -> str | None:
        return None if number in r.saved else f"não salvou o WhatsApp ({r.saved})"

    return check


def no_reintroduction(r: Run) -> str | None:
    text = last(r).lower()
    if "aqui quem fala" in text or "seja bem-vinda" in text:
        return "se apresentou de novo"
    return None


def says(pattern: str) -> Check:
    def check(r: Run) -> str | None:
        return None if re.search(pattern, last(r), re.I) else f"faltou: {pattern}"

    return check


def separate_bubbles(r: Run) -> str | None:
    """Explicação, pedido do WhatsApp e link chegam em mensagens separadas."""
    bubbles = split_bubbles(last(r))
    with_link = [b for b in bubbles if HANDOFF in b]
    if not with_link:
        return None
    if _ASKS_WHATSAPP.search(with_link[0]):
        return f"pedido de WhatsApp e link no mesmo balão ({len(bubbles)} balões)"
    if len(bubbles) < 2:
        return "tudo num balão só"
    return None


HANDOFF_CHECKS = [sends_link, asks_whatsapp, no_price, separate_bubbles]

COMMENT = {
    "comment_text": "tem no 36?",
    "private_text": (
        "Oi! Aqui é a Juliana, da Patricia Berberich 😊 Vi sua pergunta sobre "
        "numeração no post. Me passa seu WhatsApp com DDD para a Patrícia te "
        f"chamar com todos os detalhes?\n{PATRICIA_LINK}"
    ),
    "post_caption": "Scarpin Bianca em couro nude, salto 7cm",
}


@dataclass
class Case:
    name: str
    turns: list[str]
    checks: list[Check] = field(default_factory=list)
    customer_whatsapp: str | None = None
    comment_context: dict | None = None


CASES = [
    Case("preco", ["Quanto custa o scarpin nude?"], HANDOFF_CHECKS),
    Case("numero", ["Oi! Tem no 36?"], HANDOFF_CHECKS),
    Case("cores", ["Quais cores vocês têm do scarpin?"], HANDOFF_CHECKS),
    Case("frete", ["Qual o frete pra Recife?"], HANDOFF_CHECKS),
    Case("endereco", ["Onde fica a loja?"], [no_link, says(r"mato grosso")]),
    Case("faixa_numeros", ["Vocês trabalham com quais números?"], [says(r"34")]),
    Case(
        "manda_whatsapp",
        ["Quanto custa o scarpin?", "31 99999-8888"],
        [saved("31999998888"), does_not_ask_whatsapp, no_price],
    ),
    Case(
        "ja_tem_whatsapp",
        ["tem no 37 em preto?"],
        [sends_link, does_not_ask_whatsapp],
        customer_whatsapp="5531988887777",
    ),
    Case(
        "comentario_manda_numero",
        ["31 98888-7777"],
        [saved("31988887777"), no_reintroduction, does_not_ask_whatsapp],
        comment_context=COMMENT,
    ),
    Case(
        "comentario_pergunta_de_novo",
        ["mas qual o valor?"],
        [no_reintroduction, no_price, sends_link],
        comment_context=COMMENT,
    ),
]


async def run_case(case: Case) -> Run:
    saved_numbers: list[str] = []

    async def fake_set(pool, external_id, *, whatsapp):
        saved_numbers.append(re.sub(r"\D", "", whatsapp))

    graph = build_graph(checkpointer=InMemorySaver(), store=None)
    config = {"configurable": {"thread_id": str(uuid.uuid4()), "user_id": "eval"}}
    replies = []
    with (
        patch("whatsapp_langchain.agents.tools.handoff.get_pool", new=AsyncMock()),
        patch(
            "whatsapp_langchain.agents.tools.handoff.set_customer_whatsapp",
            new=fake_set,
        ),
    ):
        for text in case.turns:
            result = await graph.ainvoke(
                {
                    "messages": [HumanMessage(content=text)],
                    "username": "cliente_teste",
                    "customer_whatsapp": case.customer_whatsapp,
                    "comment_context": case.comment_context,
                },
                config=config,
            )
            content = result["messages"][-1].content
            replies.append(expand_patricia_link(str(content)))
    # O salvamento normaliza com 55 na frente; compara só o número local
    local = [n[2:] if n.startswith("55") and len(n) > 11 else n for n in saved_numbers]
    return Run(replies, local)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    total = passed = 0
    for case in [c for c in CASES if not args.only or args.only in c.name]:
        for i in range(args.repeat):
            try:
                run = await run_case(case)
                checks = [*case.checks, no_markdown_link]
                failures = [m for c in checks if (m := c(run))]
            except Exception as exc:
                run, failures = None, [f"erro: {exc!r}"]
            total += 1
            passed += not failures
            tag = f"{case.name} #{i + 1}" if args.repeat > 1 else case.name
            status = "OK   " if not failures else "FALHA"
            print(f"{status} {tag}: {'; '.join(failures)}")
            if args.verbose and run:
                for turn, reply in zip(case.turns, run.replies, strict=True):
                    print(f"      cliente: {turn}")
                    print("      juliana: " + reply.replace("\n", "\n               "))

    print(f"\n{passed}/{total} casos sem violação ({passed / max(total, 1):.0%})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
