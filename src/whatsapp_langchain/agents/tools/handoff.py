"""Ferramenta que salva o WhatsApp da cliente antes do encaminhamento humano.

Fluxo (ver SYSTEM_PROMPT, seção "Antes de encaminhar para a Patrícia"): antes
de passar o contato da Patrícia por qualquer motivo (preço, pagamento, frete,
estoque, troca...), o agente pede o WhatsApp da cliente e usa esta tool para
salvar. O número normalizado fica em `contacts.whatsapp`, visível no Painel
Admin, para a Patrícia contatar a cliente diretamente.

Resolve o remetente atual (IGSID) via `user_id` injetado no runtime — o
mesmo mecanismo das tools de memória e agenda (ver `_runtime.py`).
"""

from typing import Annotated, Any

import structlog
from langchain_core.tools import InjectedToolArg, tool

from whatsapp_langchain.agents.tools._runtime import extract_user_id
from whatsapp_langchain.shared.contacts import normalize_whatsapp, set_customer_whatsapp
from whatsapp_langchain.shared.db import get_pool

logger = structlog.get_logger()


@tool
async def save_customer_whatsapp(
    whatsapp: str,
    *,
    runtime: Annotated[Any, InjectedToolArg()] = None,
) -> str:
    """Salva o WhatsApp que a cliente informou, para a Patrícia entrar em contato.

    Use só depois que a cliente informar o número por conta própria, em
    resposta ao seu pedido (não invente nem peça um número que ela já tenha
    dado antes nesta conversa).
    """
    user_id, error = extract_user_id(runtime)
    if error:
        return error
    assert user_id is not None

    normalized = normalize_whatsapp(whatsapp)
    if normalized is None:
        return (
            "Esse número não parece um WhatsApp válido (esperado DDD + "
            "número, ex: 31999998888). Peça para a cliente confirmar com DDD."
        )

    pool = await get_pool()
    await set_customer_whatsapp(pool, user_id, whatsapp=normalized)
    logger.info("customer_whatsapp_saved", external_id=user_id)
    return "WhatsApp salvo. Agora você já pode passar o contato da Patrícia."
