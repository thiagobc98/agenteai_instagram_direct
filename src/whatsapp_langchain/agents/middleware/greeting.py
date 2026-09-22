"""Middleware que injeta saudação e contexto dinâmico no system prompt.

O ``system_prompt`` passado ao ``create_agent()`` é fixado uma única vez
quando o grafo é montado (no boot do Worker) — o horário real do dia
ficaria congelado nesse instante sem este middleware. O decorator
``dynamic_prompt`` do LangChain reexecuta a função abaixo a cada chamada
ao modelo, então o horário (fuso ``BUSINESS_TIMEZONE``) fica sempre
correto.

Três situações de saudação, decididas em código (não pelo "bom senso" do
modelo):

1. Primeira mensagem da conversa: apresentação completa.
2. Cliente que já conversou antes e só cumprimentou ("oi", "bom dia"...):
   boas-vindas de volta + pergunta de como ajudar. Nunca só a saudação.
3. Cliente que já conversou antes e escreveu outra coisa: responde ao
   pedido, sem repetir a apresentação.

Este middleware também anexa a seção "## WhatsApp da cliente"
(``agents/middleware/handoff_context.py``) na mesma string, em vez de usar um
segundo middleware ``@dynamic_prompt`` separado: cada middleware desse tipo
SUBSTITUI o system prompt inteiro (não empilha), então um segundo middleware
apagaria a saudação do primeiro. Ver `handoff_context.py` para detalhes.

Exemplo:
    from whatsapp_langchain.agents.middleware import create_greeting_middleware

    greeting = create_greeting_middleware(SYSTEM_PROMPT, intro="Aqui quem fala é a Ana")
    agent = create_agent(model=model, middleware=[greeting], ...)
"""

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.messages import HumanMessage

from whatsapp_langchain.agents.middleware.handoff_context import build_handoff_section
from whatsapp_langchain.shared.config import settings

# Trechos que compõem um cumprimento (já sem acento e em minúsculas). Se depois
# de removê-los não sobrar nada, a mensagem é só um cumprimento.
_GREETING_PATTERNS = [
    r"o+i+e*",
    r"ola+",
    r"opa+",
    r"e+ ?a+i+",
    r"hey",
    r"hello",
    r"salve",
    r"bom ?dia",
    r"boa ?tarde",
    r"boa ?noite",
    r"tudo (bem|bom|certo|joia)",
    r"td (bem|bom)",
    r"como (vai|esta|voce esta|voce vai|vc esta|vc ta|ta)",
    r"beleza",
    r"blz",
    r"gente",
    r"pessoal",
    r"querida",
    r"amiga",
    r"moca",
    r"vcs?",
    r"voces?",
]
_GREETING_RE = re.compile(r"\b(?:" + "|".join(_GREETING_PATTERNS) + r")\b")


def _greeting_word(hour: int) -> str:
    if hour < 12:
        return "Bom dia"
    if hour < 18:
        return "Boa tarde"
    return "Boa noite"


def _greeting_with_mention(greeting: str, username: str | None) -> str:
    """ "Boa tarde" -> "Boa tarde, @fulana" quando o @ da cliente é conhecido.

    Montado em código, não pelo modelo: o @ vem direto da tabela `contacts`
    (perfil real do Instagram), então não tem como sair errado ou inventado.
    """
    if not username:
        return greeting
    return f"{greeting}, @{username.lstrip('@')}"


def is_greeting_only(text: str) -> bool:
    """True se a mensagem é apenas um cumprimento (sem pergunta nem pedido).

    "Oi", "Bom dia!", "Olá, tudo bem? 😊" -> True.
    "Oi, quanto custa?", "Quem tá falando?" -> False.
    Mensagem vazia ou só com emoji -> False (não dá para saber a intenção).
    """
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = re.sub(r"[^a-z\s]", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return False
    return not _GREETING_RE.sub(" ", plain).strip()


def _last_human_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            if isinstance(content, str):
                return content
            return " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
    return ""


def build_greeting_prompt(
    system_prompt: str,
    intro: str,
    now: datetime,
    *,
    is_first_turn: bool,
    last_message: str = "",
    username: str | None = None,
    customer_whatsapp: str | None = None,
) -> str:
    """Monta o system prompt final com saudação e contexto de WhatsApp.

    Função pura (sem acesso a relógio ou estado do agente) para ser testável.

    Args:
        system_prompt: Prompt base do agente.
        intro: Apresentação da primeira mensagem (sem saudação nem pontuação).
        now: Data/hora local da loja.
        is_first_turn: True se é a primeira mensagem da cliente na conversa.
        last_message: Texto da mensagem que está sendo respondida.
        username: @ da cliente no Instagram, se já foi salvo (tabela
            `contacts`). Sem ele, a saudação sai sem menção.
        customer_whatsapp: WhatsApp da cliente já salvo (tabela `contacts`),
            ou None se ela ainda não informou — ver `handoff_context.py`.
    """
    greeting = _greeting_with_mention(_greeting_word(now.hour), username)

    if is_first_turn:
        instruction = (
            f"Esta é a primeira mensagem da conversa. Comece sua resposta "
            f'exatamente com "{greeting}! {intro}, seja bem-vinda. Como posso '
            f'te ajudar hoje?" — troque "bem-vinda" por "bem-vindo" apenas se '
            "já souber que é um homem. Não use nenhuma outra saudação "
            '(como "Olá") nesta primeira mensagem.'
        )
    elif is_greeting_only(last_message):
        instruction = (
            "Esta cliente JÁ conversou com você antes e agora só cumprimentou. "
            "NUNCA responda apenas com a saudação. Dê boas-vindas de volta e "
            "pergunte como pode ajudar, respondendo exatamente: "
            f'"{greeting}! Que bom falar com você de novo, seja bem-vinda '
            'novamente 😊 Como posso te ajudar hoje?" — troque "bem-vinda" '
            'por "bem-vindo" apenas se já souber que é um homem. Se já souber '
            "o nome dela (pela memória), pode incluí-lo logo após a saudação. "
            'Não repita a apresentação completa e não use "Olá".'
        )
    else:
        instruction = (
            "Esta cliente já conversou com você antes: não repita a "
            "apresentação. Responda direto ao que ela pediu. Se a mensagem "
            f'começar com um cumprimento, comece com "{greeting}!" e já '
            "atenda o pedido na mesma resposta."
        )

    return (
        f"{system_prompt}\n\n"
        "## Saudação\n\n"
        f"Agora são {now.strftime('%H:%M')} (horário de "
        f"{settings.business_timezone}).\n\n"
        f"{instruction}\n\n"
        f"{build_handoff_section(customer_whatsapp)}"
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
        human_count = sum(1 for m in messages if isinstance(m, HumanMessage))
        return build_greeting_prompt(
            system_prompt,
            intro,
            now,
            is_first_turn=human_count <= 1,
            last_message=_last_human_text(messages),
            username=request.state.get("username"),
            customer_whatsapp=request.state.get("customer_whatsapp"),
        )

    return inject_greeting
