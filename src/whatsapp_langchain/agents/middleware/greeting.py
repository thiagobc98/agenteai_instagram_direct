"""Middleware que injeta saudação (bom dia/boa tarde/boa noite) e a
data/hora atual no system prompt.

O ``system_prompt`` passado ao ``create_agent()`` é fixado uma única vez
quando o grafo é montado (no boot do Worker) — o horário real do dia
ficaria congelado nesse instante sem este middleware. O decorator
``dynamic_prompt`` do LangChain reexecuta a função abaixo a cada chamada
ao modelo, então o horário (fuso ``BUSINESS_TIMEZONE``) fica sempre
correto.

Exemplo:
    from whatsapp_langchain.agents.middleware import create_greeting_middleware

    greeting = create_greeting_middleware(SYSTEM_PROMPT, intro="Aqui quem fala é a Ana")
    agent = create_agent(model=model, middleware=[greeting], ...)
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.messages import HumanMessage

from whatsapp_langchain.shared.config import settings


def _greeting_word(hour: int) -> str:
    if hour < 12:
        return "Bom dia"
    if hour < 18:
        return "Boa tarde"
    return "Boa noite"


def build_greeting_prompt(
    system_prompt: str, intro: str, now: datetime, is_first_turn: bool
) -> str:
    """Monta o system prompt final com as instruções de saudação.

    Função pura (sem acesso a relógio ou estado do agente) para ser testável.
    """
    greeting = _greeting_word(now.hour)

    if is_first_turn:
        instruction = (
            f"Esta é a primeira mensagem da conversa. Comece sua resposta "
            f'exatamente com "{greeting}! {intro}, seja bem-vinda. Como posso '
            f'te ajudar hoje?" — troque "bem-vinda" por "bem-vindo" apenas se '
            "já souber que é um homem. Não use nenhuma outra saudação "
            '(como "Olá") nesta primeira mensagem.'
        )
    else:
        instruction = (
            f'Se a cliente cumprimentar novamente (ex: "oi", "bom dia") '
            f'no meio da conversa, responda ao cumprimento com "{greeting}!" '
            "sem repetir a apresentação completa (você já se apresentou)."
        )

    return (
        f"{system_prompt}\n\n"
        "## Saudação\n\n"
        f"Agora são {now.strftime('%H:%M')} (horário de "
        f"{settings.business_timezone}).\n\n"
        f"{instruction}"
    )


def create_greeting_middleware(system_prompt: str, intro: str):
    """Cria middleware que anexa instruções de saudação ao system prompt.

    Args:
        system_prompt: Prompt base do agente (ex: SYSTEM_PROMPT de prompts.py).
        intro: Como o agente se apresenta na primeira mensagem, sem saudação
            nem pontuação final (ex: "Aqui quem fala é a Juliana, atendente
            virtual da Patricia Berberich").

    Returns:
        Middleware decorado com ``@dynamic_prompt``, pronto para a lista
        `middleware=` do `create_agent()`.
    """

    @dynamic_prompt
    def inject_greeting(request: ModelRequest) -> str:
        now = datetime.now(ZoneInfo(settings.business_timezone))
        messages = request.state.get("messages", [])
        is_first_turn = sum(1 for m in messages if isinstance(m, HumanMessage)) <= 1
        return build_greeting_prompt(system_prompt, intro, now, is_first_turn)

    return inject_greeting
