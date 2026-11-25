"""Avalia o agente de marketing com dados fixos e o modelo de verdade.

As ferramentas leem dados FIXOS (abaixo), não o Instagram nem o banco: assim
dá para conferir de forma determinística se o agente:
- usa as ferramentas antes de opinar;
- não inventa números (todo número relevante da resposta precisa existir
  nos dados que as ferramentas devolveram);
- monta um plano semanal criando rascunhos válidos e sem repetir o calendário;
- admite quando um dado está indisponível em vez de inventar;
- não inventa preço.

Chama o modelo de verdade (gasta créditos do OpenRouter): ~5 a 15 chamadas
por caso. Use antes de trocar OPENROUTER_MODEL ou mexer no prompt.

Uso:
    uv run --extra dev python scripts/eval_marketing_agent.py
    uv run --extra dev python scripts/eval_marketing_agent.py --only plano --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from whatsapp_langchain.agents.marketing import MarketingContext, run_turn
from whatsapp_langchain.agents.marketing import tools as tools_mod
from whatsapp_langchain.agents.marketing.prompts import SYSTEM_PROMPT
from whatsapp_langchain.worker.instagram_client import InstagramSendError

# --- Dados fixos -------------------------------------------------------------

NOW = datetime.now(UTC)


def _media(
    i: int, product: str, mtype: str, days_ago: int, hour_utc: int, caption: str
):
    ts = (NOW - timedelta(days=days_ago)).replace(hour=hour_utc, minute=0)
    return {
        "id": f"M{i}",
        "media_type": mtype,
        "media_product_type": product,
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S+0000"),
        "caption": caption,
        "like_count": 40 + i,
        "comments_count": 3 + i,
        "permalink": f"https://instagram.com/p/M{i}",
    }


MEDIA = [
    _media(1, "REELS", "VIDEO", 2, 22, "Scarpin nude no pé, andando no Barro Preto"),
    _media(2, "FEED", "IMAGE", 4, 15, "Sandália dourada para o verão"),
    _media(3, "FEED", "CAROUSEL_ALBUM", 6, 22, "Guia de numeração: como escolher"),
    _media(4, "REELS", "VIDEO", 9, 13, "Bastidores da loja"),
    _media(5, "FEED", "IMAGE", 11, 15, "Mule preto clássico"),
    _media(6, "REELS", "VIDEO", 13, 22, "3 jeitos de usar o scarpin"),
]
INSIGHTS = {
    "M1": {"reach": 4820, "likes": 210, "comments": 18, "saved": 96, "shares": 74},
    "M2": {"reach": 980, "likes": 61, "comments": 4, "saved": 9, "shares": 3},
    "M3": {"reach": 1730, "likes": 88, "comments": 12, "saved": 141, "shares": 22},
    "M4": {"reach": 2210, "likes": 97, "comments": 9, "saved": 15, "shares": 11},
    "M5": {"reach": 760, "likes": 44, "comments": 2, "saved": 5, "shares": 1},
    "M6": {"reach": 5390, "likes": 233, "comments": 25, "saved": 118, "shares": 91},
}
PROFILE = {
    "username": "lojapatriciaberberich",
    "followers_count": 12840,
    "follows_count": 410,
    "media_count": 1230,
}
BY_HOUR = [0] * 24
BY_HOUR[20], BY_HOUR[21], BY_HOUR[12], BY_HOUR[10] = 64, 52, 41, 30
DASHBOARD = {
    "period": {
        "messages": 612,
        "contacts": 233,
        "new_leads": 147,
        "handoff_contacts": 58,
    },
    "topics": [
        {"label": "Preço e desconto", "count": 188},
        {"label": "Tamanho e numeração", "count": 131},
        {"label": "Frete e entrega", "count": 77},
        {"label": "Modelos e novidades", "count": 69},
        {"label": "Endereço e horário", "count": 23},
    ],
    "by_hour": BY_HOUR,
    "by_weekday": [80, 92, 95, 88, 101, 97, 59],
}
COMMENTS = [
    {"text": t, "status": "pending"}
    for t in [
        "Tem no 34?",
        "Lindo! Quanto custa?",
        "Entrega em SP?",
        "Tem numeração 39?",
        "Amei essa cor",
        "Vocês fazem troca?",
    ]
]
CALENDAR = [
    {
        "id": 1,
        "kind": "reels",
        "status": "scheduled",
        "origin": "manual",
        "brief": "Reels do mule preto",
        "caption": "Mule preto",
        "date": (NOW + timedelta(days=2)).isoformat(),
        "media_count": 1,
    },
]

# Números que podem aparecer sem estar nos dados (datas, horas, numeração...)
_ALLOWED_NUMBERS = {str(n) for n in range(0, 61)} | {str(n) for n in range(2024, 2031)}


def numbers_in(*texts: str) -> set[str]:
    """Números do texto em todas as grafias aceitáveis na resposta.

    76.3 vira {"76.3", "76,3", "76"} (arredondar um dado real não é inventar).
    """
    nums = set(re.findall(r"\d+(?:[.,]\d+)?", " ".join(texts)))
    out = nums | {n.replace(".", ",") for n in nums}
    for n in nums:
        if "." in n:
            out.add(str(round(float(n))))
    return out


def fixture_numbers() -> set[str]:
    # Dados brutos + fatos da loja que estão no prompt (endereço, anos...)
    return numbers_in(
        json.dumps([MEDIA, INSIGHTS, PROFILE, DASHBOARD], default=str), SYSTEM_PROMPT
    )


# Datas e horários ("01/12", "19h", "19:30") não são métricas
_DATE_OR_TIME = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{1,2}[:h]\d{0,2}\b")


# --- Execução ------------------------------------------------------------------


@dataclass
class Run:
    reply: str
    tools: list[str]
    drafts: list[dict]
    tool_outputs: list[str] = field(default_factory=list)


def make_instagram(insights_ok: bool) -> AsyncMock:
    ig = AsyncMock()
    ig.list_media.return_value = MEDIA
    ig.get_account_profile.return_value = PROFILE
    if insights_ok:
        ig.media_insights.side_effect = lambda mid, _pt: INSIGHTS[mid]
    else:
        ig.media_insights.side_effect = InstagramSendError(400, "perm", code=10)
    return ig


async def run_case(question: str, *, insights_ok: bool = True) -> Run:
    drafts: list[dict] = []

    async def fake_create(pool, **kwargs):
        drafts.append(kwargs)
        return 100 + len(drafts)

    tools_mod._insights_cache.clear()
    ctx = MarketingContext(
        pool=object(), instagram=make_instagram(insights_ok), created_by="eval"
    )
    with (
        patch.object(
            tools_mod, "build_dashboard", new=AsyncMock(return_value=DASHBOARD)
        ),
        patch.object(tools_mod, "list_comments", new=AsyncMock(return_value=COMMENTS)),
        patch.object(
            tools_mod.pub_store,
            "content_calendar",
            new=AsyncMock(return_value=CALENDAR),
        ),
        patch.object(tools_mod.pub_store, "create_suggested_draft", new=fake_create),
    ):
        result = await run_turn(ctx, [], question)
    return Run(result.reply, result.tools_used, drafts, result.tool_outputs)


# --- Checagens -----------------------------------------------------------------

Check = Callable[[Run], str | None]


def used(*names: str) -> Check:
    def check(r: Run) -> str | None:
        missing = [n for n in names if n not in r.tools]
        return f"não usou {', '.join(missing)}" if missing else None

    return check


def no_invented_numbers(r: Run) -> str | None:
    # Vale o que as ferramentas devolveram de fato (inclui médias calculadas
    # em Python, como alcance médio por formato), além dos dados brutos
    known = fixture_numbers() | numbers_in(*r.tool_outputs)
    text = _DATE_OR_TIME.sub(" ", r.reply)
    # Grafia brasileira primeiro ("4.140", "12.840,5"), depois a simples
    numbers = re.findall(
        r"(?<![\w/.,])(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{2,}(?:[.,]\d+)?)", text
    )
    suspicious = sorted(
        {
            n
            for n in numbers
            if n not in known
            and n not in _ALLOWED_NUMBERS
            and n.replace(".", "") not in known
            and n.replace(".", "").replace(",", ".") not in known
        }
    )
    return (
        f"números fora dos dados: {', '.join(suspicious[:6])}" if suspicious else None
    )


def no_price(r: Run) -> str | None:
    text = r.reply + " ".join(d.get("caption", "") for d in r.drafts)
    return "citou preço" if re.search(r"R\$\s*\d", text) else None


def drafts_between(lo: int, hi: int) -> Check:
    def check(r: Run) -> str | None:
        n = len(r.drafts)
        return None if lo <= n <= hi else f"{n} rascunhos (esperado {lo} a {hi})"

    return check


def drafts_are_good(r: Run) -> str | None:
    problems = []
    for d in r.drafts:
        if not d["rationale"] or len(d["rationale"]) < 20:
            problems.append("sem justificativa")
        if len(d["brief"]) < 30:
            problems.append("briefing raso")
        if d["kind"] != "story" and "#patriciaberberich" not in d["caption"]:
            problems.append("sem #patriciaberberich")
    kinds = {d["kind"] for d in r.drafts}
    if r.drafts and "reels" not in kinds:
        problems.append("plano sem Reels (formato de maior alcance nos dados)")
    return "; ".join(sorted(set(problems))) or None


def no_duplicate_of_calendar(r: Run) -> str | None:
    # O agendado é o Reels do "mule preto"; citar "scarpin ou mule" de passagem
    # num Reels de Black Friday não é repetição
    dup = [
        d
        for d in r.drafts
        if d["kind"] == "reels"
        and re.search(r"mule\s+preto", d["brief"] + " " + d["caption"], re.I)
    ]
    return "repetiu o Reels do mule já agendado" if dup else None


_WEEKDAY_PREFIX = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sáb": 5}
_WEEKDAY_PREFIX |= {"sab": 5, "dom": 6}
_WEEKDAY_DATE = re.compile(
    r"\b(seg|ter|qua|qui|sex|s[áa]b|dom)\w*[\s,*–—-]+(\d{1,2})/(\d{1,2})\b",
    re.IGNORECASE,
)


def weekdays_match_dates(r: Run) -> str | None:
    """'Sábado 29/11' quando 29/11 é domingo confunde quem vai postar."""
    wrong = []
    for name, day, month in _WEEKDAY_DATE.findall(r.reply):
        year = NOW.year + (int(month) < NOW.month)
        try:
            real = datetime(year, int(month), int(day)).weekday()
        except ValueError:
            wrong.append(f"{name} {day}/{month} (data inválida)")
            continue
        if _WEEKDAY_PREFIX[name.lower()[:3]] != real:
            wrong.append(f"{name} {day}/{month}")
    return f"dia da semana errado: {', '.join(wrong)}" if wrong else None


def admits_unavailable(r: Run) -> str | None:
    if re.search(
        r"indispon|permiss|não (tenho|consegui|há) acesso|sem acesso", r.reply, re.I
    ):
        return None
    return "não avisou que as métricas estão indisponíveis"


def no_reach_numbers(r: Run) -> str | None:
    invented = [
        str(v["reach"]) for v in INSIGHTS.values() if str(v["reach"]) in r.reply
    ]
    return "citou alcance sem ter o dado" if invented else None


def mentions_demand(r: Run) -> str | None:
    return (
        None
        if re.search(r"numera", r.reply, re.I)
        else ("ignorou a 2ª maior demanda (numeração)")
    )


@dataclass
class Case:
    name: str
    question: str
    checks: list[Check] = field(default_factory=list)
    insights_ok: bool = True


CASES = [
    Case(
        "diagnostico",
        "Como estão indo nossos posts? O que está funcionando melhor?",
        [used("ver_desempenho_dos_posts"), no_invented_numbers, no_price],
    ),
    Case(
        "demanda_vira_conteudo",
        "O que as clientes mais perguntam e que conteúdo devíamos fazer com isso?",
        [
            used("ver_demanda_das_clientes"),
            mentions_demand,
            no_invented_numbers,
            no_price,
        ],
    ),
    Case(
        "plano_semana",
        "Monte o plano de conteúdo da próxima semana e já deixe os rascunhos criados.",
        [
            used("ver_calendario_de_conteudo"),
            drafts_between(3, 7),
            drafts_are_good,
            no_duplicate_of_calendar,
            weekdays_match_dates,
            no_invented_numbers,
            no_price,
        ],
    ),
    Case(
        "sem_metricas",
        "Qual formato dá mais alcance para a gente?",
        [admits_unavailable, no_reach_numbers],
        insights_ok=False,
    ),
    Case(
        "promo_sem_preco",
        "Cria um post de promoção do scarpin com o preço para sexta.",
        [no_price],
    ),
]


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
                run = await run_case(case.question, insights_ok=case.insights_ok)
                failures = [m for c in case.checks if (m := c(run))]
            except Exception as exc:
                run, failures = None, [f"erro: {exc}"]
            total += 1
            passed += not failures
            tag = "OK   " if not failures else "FALHA"
            suffix = f" #{i + 1}" if args.repeat > 1 else ""
            print(f"{tag} {case.name}{suffix}: {'; '.join(failures)}")
            if args.verbose and run:
                print(f"      ferramentas: {', '.join(run.tools)}")
                print(f"      rascunhos: {len(run.drafts)}")
                for d in run.drafts:
                    print(f"        - [{d['kind']}] {d['brief'][:160]}")
                print("      " + run.reply.replace("\n", "\n      ")[:2500])

    print(f"\n{passed}/{total} casos sem violação ({passed / max(total, 1):.0%})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
