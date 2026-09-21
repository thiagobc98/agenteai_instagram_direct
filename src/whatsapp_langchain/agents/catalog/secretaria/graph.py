"""Grafo para uso com langgraph dev.

Este arquivo exporta uma variável `graph` para integração com `langgraph dev`.
O servidor de produção usa `build_graph()` de agent.py, passando o checkpointer
e store reais.

Sob `langgraph dev`/LangGraph API a plataforma gerencia checkpointer e store
automaticamente — um store customizado aqui seria rejeitado no carregamento
do grafo. As tools de memória continuam habilitadas; elas resolvem o store
via InjectedStore em runtime, usando o store que a plataforma injeta.
"""

from whatsapp_langchain.agents.catalog.secretaria.agent import build_graph

# Grafo compilado para langgraph dev — sem checkpointer/store customizados,
# a plataforma injeta os seus automaticamente.
graph = build_graph(enable_memory_tools=True)
