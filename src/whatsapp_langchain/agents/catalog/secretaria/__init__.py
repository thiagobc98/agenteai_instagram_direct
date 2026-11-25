"""Agente secretaria - atendente virtual da loja Patricia Berberich (Instagram).

Este é o agente padrão do projeto, usado como exemplo e template
para criar novos agentes.

Uso:
    from whatsapp_langchain.agents.catalog.secretaria import build_graph

    agent = build_graph()
    result = agent.invoke({"messages": [{"role": "user", "content": "Olá!"}]})
"""

from .agent import build_graph
from .prompts import SYSTEM_PROMPT

__all__ = ["build_graph", "SYSTEM_PROMPT"]
