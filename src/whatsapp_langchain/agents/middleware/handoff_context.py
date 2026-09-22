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

Não é um middleware próprio: `build_handoff_section()` é chamado de dentro do
`create_greeting_middleware()` (agents/middleware/greeting.py) e concatenado
na mesma string de system prompt. Dois middlewares `@dynamic_prompt`
independentes não compõem — cada um SUBSTITUI o system prompt inteiro, então
o segundo apagaria a saudação do primeiro. Ver o aviso na docstring de
`greeting.py`.
"""

PATRICIA_CONTACT = "31 993456562"

# Depois de pedir o WhatsApp esse número de vezes sem sucesso, o bot desiste
# de insistir e encaminha para a Patrícia mesmo sem o número salvo.
MAX_WHATSAPP_ASKS = 2


def build_handoff_section(customer_whatsapp: str | None, ask_count: int = 0) -> str:
    """Monta a seção "## WhatsApp da cliente" do system prompt.

    Args:
        customer_whatsapp: WhatsApp da cliente já salvo (`contacts.whatsapp`),
            ou None se ela ainda não informou.
        ask_count: Quantas vezes o agente já pediu o WhatsApp nesta conversa
            (contado em código, ver `greeting.py`). Ignorado se
            `customer_whatsapp` já estiver preenchido.
    """
    if customer_whatsapp:
        return (
            "## WhatsApp da cliente\n\n"
            "Você JÁ TEM o WhatsApp desta cliente salvo. Não peça de novo. "
            "Quando for encaminhar para a Patrícia por qualquer motivo, pode "
            f"informar o contato dela diretamente ({PATRICIA_CONTACT})."
        )
    if ask_count >= MAX_WHATSAPP_ASKS:
        return (
            "## WhatsApp da cliente\n\n"
            f"Você já pediu o WhatsApp desta cliente {ask_count} vezes nesta "
            "conversa e ela não passou. NÃO peça de novo — desista de "
            "insistir. Quando for encaminhar para a Patrícia, informe o "
            f"contato dela ({PATRICIA_CONTACT}) mesmo sem o WhatsApp da "
            "cliente, para não perder o atendimento. Não use a tool "
            "save_customer_whatsapp (não há número para salvar)."
        )
    return (
        "## WhatsApp da cliente\n\n"
        "Você ainda NÃO tem o WhatsApp desta cliente salvo. Siga a seção "
        '"Antes de encaminhar para a Patrícia" do seu prompt: peça o WhatsApp '
        f"dela antes de informar o contato da Patrícia ({PATRICIA_CONTACT}). "
        "Quando ela informar o número, use a tool save_customer_whatsapp "
        "para salvar antes de continuar."
    )
