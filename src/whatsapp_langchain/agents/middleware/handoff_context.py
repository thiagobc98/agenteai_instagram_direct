"""Trecho de instrução sobre o WhatsApp da cliente, injetado no system prompt.

Decide em código (não pelo "bom senso" do modelo) se o agente já tem o
WhatsApp da cliente salvo — fato que vem do banco (`contacts.whatsapp`), não
do que sobrou visível no histórico da conversa (que pode ter sido resumido ou
cortado pelo middleware de contexto).

Não é um middleware próprio: `build_handoff_section()` é chamado de dentro do
`create_greeting_middleware()` (agents/middleware/greeting.py) e concatenado
na mesma string de system prompt. Dois middlewares `@dynamic_prompt`
independentes não compõem — cada um SUBSTITUI o system prompt inteiro, então
o segundo apagaria a saudação do primeiro. Ver o aviso na docstring de
`greeting.py`.
"""

PATRICIA_CONTACT = "31 993456562"


def build_handoff_section(customer_whatsapp: str | None) -> str:
    """Monta a seção "## WhatsApp da cliente" do system prompt.

    Args:
        customer_whatsapp: WhatsApp da cliente já salvo (`contacts.whatsapp`),
            ou None se ela ainda não informou.
    """
    if customer_whatsapp:
        return (
            "## WhatsApp da cliente\n\n"
            "Você JÁ TEM o WhatsApp desta cliente salvo. Não peça de novo. "
            "Quando for encaminhar para a Patrícia por qualquer motivo, pode "
            f"informar o contato dela diretamente ({PATRICIA_CONTACT})."
        )
    return (
        "## WhatsApp da cliente\n\n"
        "Você ainda NÃO tem o WhatsApp desta cliente salvo. Siga a seção "
        '"Antes de encaminhar para a Patrícia" do seu prompt: peça o WhatsApp '
        f"dela antes de informar o contato da Patrícia ({PATRICIA_CONTACT}). "
        "Quando ela informar o número, use a tool save_customer_whatsapp "
        "para salvar antes de continuar."
    )
