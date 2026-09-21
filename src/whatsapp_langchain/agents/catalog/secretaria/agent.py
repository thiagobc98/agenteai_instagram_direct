"""Agente secretaria - assistente da comunidade Top Hawks.

Agente simples usando create_agent do LangChain 1.0.
Usa middleware de contexto configurável (trim ou summarize)
e memória semântica cross-thread via LangGraph Store.

Este arquivo contém a factory `build_graph()`. Para langgraph dev,
veja graph.py que exporta a variável `graph`.

Configuração via .env:
    OPENROUTER_API_KEY=sk-or-...       # API key do OpenRouter
    OPENROUTER_MODEL=anthropic/...     # Modelo principal
    CONTEXT_STRATEGY=trim              # trim | summarize | none
    TRIM_KEEP_TURNS=5                  # Turnos a manter (trim)
    SUMMARIZE_TRIGGER_TOKENS=4000      # Tokens antes de sumarizar
    SUMMARIZE_KEEP_MESSAGES=10         # Mensagens após sumarização
    SUMMARIZE_MODEL=anthropic/...      # Modelo para sumarização
    MEMORY_ENABLED=true                # Habilita memória semântica
"""

from langchain.agents import create_agent
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from whatsapp_langchain.agents.middleware import (
    create_greeting_middleware,
    get_context_middleware,
)
from whatsapp_langchain.agents.tools import (
    book_appointment,
    cancel_appointment,
    check_availability,
    get_current_date,
    list_my_appointments,
    read_memory,
    reschedule_appointment,
    save_memory,
)
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.llm import create_chat_model

from .prompts import SYSTEM_PROMPT


def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    enable_memory_tools: bool | None = None,
):
    """Constrói o agente secretaria.

    O agente usa middleware de contexto configurável via CONTEXT_STRATEGY:
    - trim: Remove mensagens antigas (custo zero, perde contexto)
    - summarize: Sumariza mensagens antigas (custo extra, preserva contexto)
    - none: Sem gerenciamento de contexto

    Se a memória semântica estiver habilitada:
    - Recall automático via middleware (busca memórias antes de cada chamada)
    - Save explícito via tool save_memory (agente decide quando salvar)

    Args:
        checkpointer: Checkpointer para persistência de estado.
                      None em dev (in-memory), PostgresSaver em prod.
        store: Store para memória semântica cross-thread.
               None desabilita memória, InMemoryStore em dev,
               AsyncPostgresStore em prod. Não deve ser usado sob
               `langgraph dev`/LangGraph API — a plataforma injeta seu
               próprio store automaticamente em runtime.
        enable_memory_tools: Sobrepõe a decisão de habilitar as tools de
                      memória. Por padrão segue `store is not None`.

    Returns:
        CompiledStateGraph: Agente compilado pronto para uso.
    """
    # Modelo principal com rate limiter centralizado (shared/llm.py)
    model = create_chat_model()

    # Middleware de contexto baseado em CONTEXT_STRATEGY, mais a saudação
    # dinâmica (bom dia/tarde/noite) recalculada a cada chamada ao modelo
    middleware = [*get_context_middleware(), create_greeting_middleware(SYSTEM_PROMPT)]

    if enable_memory_tools is None:
        enable_memory_tools = store is not None

    # Tools de memória — resolvem o store via InjectedStore em runtime
    tools = [save_memory, read_memory] if enable_memory_tools else []

    # Tools de agendamento (Google Calendar) — só habilitadas se configuradas
    if settings.google_calendar_enabled:
        tools += [
            get_current_date,
            check_availability,
            book_appointment,
            reschedule_appointment,
            cancel_appointment,
            list_my_appointments,
        ]

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        checkpointer=checkpointer,
        store=store,
    )
