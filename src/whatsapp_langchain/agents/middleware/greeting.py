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

    greeting = create_greeting_middleware(SYSTEM_PROMPT)
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


def create_greeting_middleware(system_prompt: str):
    """Cria middleware que anexa instruções de saudação ao system prompt.

    Args:
        system_prompt: Prompt base do agente (ex: SYSTEM_PROMPT de prompts.py).

    Returns:
        Middleware decorado com ``@dynamic_prompt``, pronto para a lista
        `middleware=` do `create_agent()`.
    """

    @dynamic_prompt
    def inject_greeting(request: ModelRequest) -> str:
        now = datetime.now(ZoneInfo(settings.business_timezone))
        greeting = _greeting_word(now.hour)

        messages = request.state.get("messages", [])
        is_first_turn = sum(1 for m in messages if isinstance(m, HumanMessage)) <= 1

        if is_first_turn:
            instruction = (
                f'Esta é a primeira mensagem da conversa. Comece sua resposta '
                f'exatamente com "{greeting}! Aqui quem fala é a secretária da '
                f'Dra. Luana Lima, seja bem-vindo(a). O que posso ajudar você '
                f'hoje?" — ajuste "bem-vindo(a)" para o gênero do paciente '
                "apenas se já for conhecido. Não use nenhuma outra saudação "
                "(como \"Olá\") nesta primeira mensagem."
            )
        else:
            instruction = (
                f'Se o paciente cumprimentar novamente (ex: "oi", "bom dia") '
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

    return inject_greeting
