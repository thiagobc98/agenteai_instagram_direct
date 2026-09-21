"""Processador de mensagens — orquestra agente, typing e envio Evolution API.

Responsável por:
1. Pré-processar entrada (mídia -> texto)
2. Enviar typing indicator (best-effort)
3. Carregar o agente via loader (com checkpointer PostgreSQL)
4. Executar o agente
5. Enviar resposta ao usuário via Evolution API
6. Salvar no banco (mark_done somente após envio confirmado)

Decisões arquiteturais (Fase 3):
- Envio confirmado é obrigatório — não existe caminho sem envio confirmado.
- Typing é tentado em 100% das execuções normais (best-effort).
- Falha de typing NÃO interrompe o processamento.
- mark_done ocorre somente após envio bem-sucedido.
- Falha de envio entra no fluxo de retry (mark_failed).

Uso:
    from whatsapp_langchain.worker.processor import process_message

    await process_message(
        message, pool,
        checkpointer=checkpointer,
        store=store,
        evolution=evolution,
    )
"""

import structlog
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.agents.loader import load_graph
from whatsapp_langchain.shared.models import MessageQueue
from whatsapp_langchain.shared.queue import (
    mark_done,
    mark_failed,
    upsert_conversation,
)
from whatsapp_langchain.worker.evolution_client import EvolutionClient
from whatsapp_langchain.worker.media import (
    AUTO_RESPONSE_MEDIA_FAILURE,
    preprocess_incoming_message,
)

logger = structlog.get_logger()


async def process_message(
    message: MessageQueue,
    pool: AsyncConnectionPool,
    *,
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
    evolution: EvolutionClient,
) -> None:
    """Processa uma mensagem da fila com o agente apropriado.

    Decodifica mídia base64 se presente, envia typing, carrega o grafo
    do agente com checkpointer PostgreSQL, executa, envia a resposta
    via Evolution API e salva no banco.

    Envio confirmado é obrigatório — nenhum mark_done ocorre sem isso.

    Args:
        message: Mensagem a processar (já reservada via claim).
        pool: Pool de conexões do psycopg.
        checkpointer: Checkpointer LangGraph já inicializado no boot.
        store: Store LangGraph compartilhado (None se memória desabilitada).
        evolution: Cliente Evolution API para envio (obrigatório).
    """
    logger.info(
        "processing_message",
        message_id=message.id,
        phone=message.phone_number,
        agent_id=message.agent_id,
        attempt=message.attempts,
    )

    try:
        # 1. Pré-processar entrada (mídia -> texto) antes do agente
        pre = await preprocess_incoming_message(
            body=message.incoming_message,
            media_base64=message.media_base64,
            media_type=message.media_type,
        )

        # Se mídia está desabilitada ou falhou, não chama o agente
        if not pre.should_invoke_agent:
            auto_response = pre.auto_response or AUTO_RESPONSE_MEDIA_FAILURE

            # Enviar auto-response antes de marcar como done
            await evolution.send_message(message.phone_number, auto_response)

            await mark_done(
                pool,
                message.id,
                auto_response,
                normalized_input=None,
                media_processing_status=pre.media_processing_status,
                media_processing_error=pre.media_processing_error,
            )
            await upsert_conversation(
                pool,
                phone_number=message.phone_number,
                agent_id=message.agent_id,
                last_message=auto_response,
            )
            logger.info(
                "message_auto_responded",
                message_id=message.id,
                phone=message.phone_number,
                agent_id=message.agent_id,
                media_status=pre.media_processing_status,
            )
            return

        # 2. Typing indicator (best-effort, falha não interrompe processamento)
        try:
            await evolution.send_typing(message.phone_number)
        except Exception as typing_err:
            logger.warning(
                "typing_failed",
                message_id=message.id,
                phone=message.phone_number,
                error=str(typing_err),
            )

        # 3. Carregar agente com checkpointer + store (se memória habilitada)
        normalized_text = pre.normalized_text or message.incoming_message
        human_message = HumanMessage(content=normalized_text)

        invoke_config = {
            "configurable": {
                "thread_id": message.thread_id,
                "user_id": message.phone_number,
            }
        }

        graph = load_graph(
            message.agent_id,
            checkpointer=checkpointer,
            store=store,
        )
        result = await graph.ainvoke(
            {"messages": [human_message]},
            config=invoke_config,
        )

        # 4. Extrair resposta
        response_text = result["messages"][-1].content

        # 5. Enviar resposta via Evolution API (obrigatório antes de mark_done)
        await evolution.send_message(message.phone_number, response_text)

        # 6. mark_done somente após envio confirmado
        await mark_done(
            pool,
            message.id,
            response_text,
            normalized_input=pre.normalized_text,
            media_processing_status=pre.media_processing_status,
            media_processing_error=pre.media_processing_error,
        )
        await upsert_conversation(
            pool,
            phone_number=message.phone_number,
            agent_id=message.agent_id,
            last_message=response_text,
        )

        logger.info(
            "message_processed",
            message_id=message.id,
            phone=message.phone_number,
            agent_id=message.agent_id,
            response_length=len(response_text),
        )

    except Exception as e:
        logger.error(
            "message_processing_error",
            message_id=message.id,
            phone=message.phone_number,
            agent_id=message.agent_id,
            error=str(e),
        )
        await mark_failed(pool, message.id, str(e))
