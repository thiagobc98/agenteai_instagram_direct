"""Agente de marketing: estrategista de conteúdo e crescimento do Instagram.

Conversa com a EQUIPE no painel (tela Marketing), nunca com clientes. Fica
fora de `agents/catalog/` de propósito: o catálogo é exposto ao webhook do
Direct (`?agent=...`), e este agente não pode ser acionado por cliente.

Usa dados reais via ferramentas (desempenho dos posts, perfil, demanda das
clientes no Direct e nos comentários, calendário de conteúdo, datas
comerciais) e cria RASCUNHOS na tela Publicar. Nada é publicado sem a
equipe subir a mídia e aprovar.
"""

from whatsapp_langchain.agents.marketing.agent import TurnResult, run_turn
from whatsapp_langchain.agents.marketing.tools import MarketingContext

__all__ = ["MarketingContext", "TurnResult", "run_turn"]
