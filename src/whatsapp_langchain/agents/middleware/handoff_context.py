"""Trecho de instrução sobre o WhatsApp da cliente, injetado no system prompt.

Decide em código (não pelo "bom senso" do modelo):

- Se o agente já tem o WhatsApp da cliente salvo — fato que vem do banco
  (`contacts.whatsapp`), não do que sobrou visível no histórico da conversa
  (que pode ter sido resumido ou cortado pelo middleware de contexto).
- Quantas vezes o agente já pediu o WhatsApp nesta conversa — contado a
  partir do histórico de mensagens (`AIMessage`s que mencionam "WhatsApp"),
  não confiado ao modelo contar sozinho. Testes com o modelo real mostraram
  que ele não desiste de insistir de forma confiável se tiver que contar por
  conta própria; por isso a decisão de pedir, insistir mais uma vez ou
  desistir é sempre dada pronta aqui.

Fluxo de encaminhamento: na MESMA mensagem o agente pede o WhatsApp da
cliente (para a Patrícia chamar) e já manda o link do WhatsApp da Patrícia
(para a cliente chamar direto, se preferir). O link vem pronto daqui, montado
a partir de `settings.handoff_phone`: o modelo nunca escreve o número.

Não é um middleware próprio: `build_handoff_section()` é chamado de dentro do
`create_greeting_middleware()` (agents/middleware/greeting.py) e concatenado
na mesma string de system prompt. Dois middlewares `@dynamic_prompt`
independentes não compõem — cada um SUBSTITUI o system prompt inteiro, então
o segundo apagaria a saudação do primeiro. Ver o aviso na docstring de
`greeting.py`.
"""

import re
from urllib.parse import quote

from whatsapp_langchain.shared.config import settings

# Depois de pedir o WhatsApp esse número de vezes sem sucesso, o bot para de
# pedir e só manda o link da Patrícia.
MAX_WHATSAPP_ASKS = 2

# Mensagem que já vem escrita quando a cliente abre o link: a Patrícia sabe
# de onde ela veio sem precisar perguntar.
PREFILLED_TEXT = "Oi, Patrícia! Vim pelo Instagram da loja 😊"


def whatsapp_link(phone: str, text: str = PREFILLED_TEXT) -> str:
    """Link wa.me para o telefone (DDD + número; o 55 é colocado se faltar)."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) in (10, 11):
        digits = "55" + digits
    link = f"https://wa.me/{digits}"
    return f"{link}?text={quote(text)}" if text else link


# O modelo escreve o link curto (fácil de copiar sem erro); antes de enviar,
# `expand_patricia_link()` troca pelo link completo, com a mensagem pronta.
PATRICIA_LINK = whatsapp_link(settings.handoff_phone, text="")
PATRICIA_FULL_LINK = whatsapp_link(settings.handoff_phone)


def expand_patricia_link(text: str) -> str:
    """Troca o link curto da Patrícia (com ou sem parâmetros, com ou sem
    https://) pelo link completo. Outros links ficam como estão."""
    if not text:
        return text
    digits = PATRICIA_LINK.rsplit("/", 1)[1]
    pattern = rf"(?:https?://)?(?:api\.)?wa\.me/{digits}(?:[/?][^\s)\]]*)?"
    return re.sub(pattern, PATRICIA_FULL_LINK, text)


def build_handoff_section(customer_whatsapp: str | None, ask_count: int = 0) -> str:
    """Monta a seção "## WhatsApp da cliente" do system prompt.

    Args:
        customer_whatsapp: WhatsApp da cliente já salvo (`contacts.whatsapp`),
            ou None se ela ainda não informou.
        ask_count: Quantas vezes o agente já pediu o WhatsApp nesta conversa
            (contado em código, ver `greeting.py`). Ignorado se
            `customer_whatsapp` já estiver preenchido.
    """
    link = (
        "Link do WhatsApp da Patrícia (copie exatamente, sem markdown): "
        f"{PATRICIA_LINK}"
    )
    if customer_whatsapp:
        return (
            "## WhatsApp da cliente\n\n"
            "Você JÁ TEM o WhatsApp desta cliente salvo. Não peça de novo. "
            "Quando for encaminhar para a Patrícia, diga que ela vai chamar a "
            "cliente no WhatsApp e mande o link abaixo, caso a cliente prefira "
            f"chamar direto.\n\n{link}"
        )
    if ask_count >= MAX_WHATSAPP_ASKS:
        return (
            "## WhatsApp da cliente\n\n"
            f"Você já pediu o WhatsApp desta cliente {ask_count} vezes nesta "
            "conversa e ela não passou. NÃO peça de novo — desista de "
            "insistir. Quando for encaminhar para a Patrícia, mande só o link "
            "abaixo, para a cliente chamar a Patrícia direto. Não use a tool "
            "save_customer_whatsapp (não há número para salvar).\n\n"
            f"{link}"
        )
    return (
        "## WhatsApp da cliente\n\n"
        "Você ainda NÃO tem o WhatsApp desta cliente salvo. Quando for "
        "encaminhar para a Patrícia, na MESMA mensagem: peça o WhatsApp dela "
        "com DDD, para a Patrícia chamar, e mande o link abaixo, caso ela "
        "prefira chamar a Patrícia direto. Quando ela informar o número, use "
        "a tool save_customer_whatsapp para salvar antes de responder.\n\n"
        f"{link}"
    )
