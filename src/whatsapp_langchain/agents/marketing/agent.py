"""Execução de um turno do agente de marketing.

Não usa checkpointer: o histórico vem da tabela `marketing_messages` (só o
texto de usuário e assistente, últimas N mensagens). Assim:
- o contexto fica limitado e previsível (custo e latência controlados);
- dados velhos de ferramenta não "contaminam" respostas novas: o agente
  consulta as ferramentas de novo a cada pergunta.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from whatsapp_langchain.agents.marketing.prompts import SYSTEM_PROMPT
from whatsapp_langchain.agents.marketing.tools import MarketingContext, build_tools
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.llm import create_chat_model

WEEKDAYS = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]

# Mensagens anteriores (usuário + assistente) enviadas ao modelo
HISTORY_LIMIT = 12
# Teto de passos do agente (cada chamada de ferramenta conta 2)
RECURSION_LIMIT = 30
TURN_TIMEOUT_SECONDS = 150


@dataclass
class TurnResult:
    reply: str
    tools_used: list[str]
    # Texto exato que as ferramentas devolveram ao modelo neste turno. É a
    # base de verdade para conferir se a resposta cita só números reais.
    tool_outputs: list[str] = field(default_factory=list)


def today_line(now: datetime | None = None) -> str:
    tz = ZoneInfo(settings.business_timezone)
    now = now or datetime.now(tz)
    upcoming = ", ".join(
        f"{_WEEKDAY_SHORT[d.weekday()]} {d.strftime('%d/%m')}"
        for d in (now + timedelta(days=i) for i in range(1, CALENDAR_DAYS + 1))
    )
    return (
        f"{WEEKDAYS[now.weekday()]}, {now.strftime('%d/%m/%Y %H:%M')} "
        f"(horário de Brasília). Datas sugeridas precisam ser a partir de agora.\n"
        f"Próximos dias (use exatamente estes dias da semana, não calcule): "
        f"{upcoming}."
    )


def build_messages(history: list[dict], question: str) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history[-HISTORY_LIMIT:]:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            messages.append(AIMessage(content=item["content"]))
    messages.append(HumanMessage(content=question))
    return messages


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return str(content)


def _final_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage) and _text(m.content).strip():
            return _text(m.content).strip()
    return ""


# Promessa ("vou criar os rascunhos", "criarei") ou afirmação ("criei",
# "rascunhos já criados", "deixei na tela Publicar"). Só é checado quando
# nenhum rascunho foi criado de fato no turno; pergunta ("quer que eu crie?")
# não casa.
_CREATION_CLAIM = re.compile(
    r"\b(?:vou|irei|vamos)\s+(?:j[áa]\s+)?(?:criar|deixar|montar|gerar|cadastrar)\b"
    r"|\b(?:criarei|deixarei|criei|cadastrei)\b"
    r"|\bdeixei\b[^.\n]{0,40}\b(?:rascunho|publicar)"
    r"|\brascunhos?\b[^.\n]{0,20}\bcriad[oa]s?\b",
    re.IGNORECASE,
)

CREATE_NUDGE = (
    "[Aviso do sistema] Sua resposta diz que criou ou vai criar rascunhos, mas "
    "nenhum foi criado: a ferramenta criar_rascunho_de_post não foi chamada. Se a "
    "equipe pediu os rascunhos, crie-os agora (uma chamada por post) e depois "
    "responda dizendo o que foi criado. Se você está aguardando confirmação da "
    "equipe, responda apenas perguntando, sem dizer que criou ou vai criar."
)

UNKEPT_PROMISE_NOTE = (
    "\n\n_Atenção: nenhum rascunho foi criado nesta resposta. "
    'Peça "crie os rascunhos" para eu criar._'
)

# Dias à frente listados com o dia da semana (o modelo erra essa conta)
CALENDAR_DAYS = 14
_WEEKDAY_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


_KIND_LABEL = {"feed": "Feed", "story": "Story", "reels": "Reels"}


def drafts_summary(actions: list[dict]) -> str:
    """Resposta montada pelo código a partir dos rascunhos realmente criados."""
    drafts = [a for a in actions if a.get("type") == "draft"]
    tz = ZoneInfo(settings.business_timezone)
    lines = []
    for a in sorted(drafts, key=lambda a: a["planned_for"]):
        when = datetime.fromisoformat(a["planned_for"]).astimezone(tz)
        day = f"{_WEEKDAY_SHORT[when.weekday()]} {when.strftime('%d/%m %H:%M')}"
        kind = _KIND_LABEL.get(a["kind"], a["kind"])
        lines.append(f"- **{day}** · {kind}: {a['title']}")
    plural = "s" if len(drafts) > 1 else ""
    return (
        f"Criei {len(drafts)} rascunho{plural} na tela Publicar:\n\n"
        + "\n".join(lines)
        + "\n\nAbra cada um para ver o briefing, a legenda e a justificativa, subir "
        "a mídia e aprovar."
    )


def promised_drafts(reply: str) -> bool:
    """True se a resposta promete ou afirma ter criado rascunhos."""
    return bool(_CREATION_CLAIM.search(reply))


async def run_turn(
    ctx: MarketingContext, history: list[dict], question: str
) -> TurnResult:
    """Roda uma pergunta da equipe e devolve a resposta final do agente.

    Raises:
        asyncio.TimeoutError: Se passar de TURN_TIMEOUT_SECONDS.
    """
    agent = create_agent(
        model=create_chat_model(temperature=0.5),
        tools=build_tools(ctx),
        system_prompt=SYSTEM_PROMPT.replace("{today}", today_line()),
    )
    config = {"recursion_limit": RECURSION_LIMIT}
    async with asyncio.timeout(TURN_TIMEOUT_SECONDS):
        state = await agent.ainvoke(
            {"messages": build_messages(history, question)}, config=config
        )
        messages = state["messages"]
        # Autocorreção (no máximo uma vez): o modelo anunciou que ia criar
        # rascunhos mas encerrou sem chamar a ferramenta
        if ctx.drafts_created == 0 and promised_drafts(_final_text(messages)):
            state = await agent.ainvoke(
                {"messages": [*messages, HumanMessage(content=CREATE_NUDGE)]},
                config=config,
            )
            messages = state["messages"]

    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    tools_used = [m.name for m in tool_messages if m.name]
    reply = _final_text(messages)
    if not reply and ctx.drafts_created:
        # O modelo encerrou depois das ferramentas sem texto final: em vez de
        # um erro, resume o que foi feito de verdade
        reply = drafts_summary(ctx.actions)
    elif not reply:
        reply = "Não consegui montar uma resposta agora. Pode reformular a pergunta?"
    elif ctx.drafts_created == 0 and promised_drafts(reply):
        reply += UNKEPT_PROMISE_NOTE
    return TurnResult(
        reply=reply,
        tools_used=list(dict.fromkeys(tools_used)),
        tool_outputs=[_text(m.content) for m in tool_messages],
    )
