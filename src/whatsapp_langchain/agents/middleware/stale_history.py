"""Middleware que esconde do modelo respostas antigas que não valem mais.

O histórico de cada conversa fica salvo no banco (checkpointer). Respostas
geradas antes de uma correção de persona — ex.: "Aqui quem fala é a secretária da
Dra. Luana Lima", de quando o agente ainda era de uma clínica — continuam lá, e o
modelo tende a imitar o que vê no histórico.

Em vez de reescrever o banco, este middleware remove essas mensagens da entrada do
modelo a cada chamada. O histórico salvo não é alterado.

Exemplo:
    from whatsapp_langchain.agents.middleware import create_stale_history_filter

    stale = create_stale_history_filter(("Dra. Luana Lima",))
    agent = create_agent(model=model, middleware=[stale], ...)
"""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, BaseMessage


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(
        part.get("text", "") if isinstance(part, dict) else str(part)
        for part in content
    )


def drop_stale_messages(
    messages: list[BaseMessage], markers: tuple[str, ...]
) -> list[BaseMessage]:
    """Remove respostas do assistente que contêm algum dos `markers`.

    Comparação sem diferenciar maiúsculas. Mensagens com chamadas de tool são
    mantidas: removê-las deixaria a resposta da tool órfã.
    """
    lowered = tuple(m.lower() for m in markers if m)

    def is_stale(message: BaseMessage) -> bool:
        if not isinstance(message, AIMessage) or message.tool_calls:
            return False
        text = _text(message).lower()
        return any(marker in text for marker in lowered)

    return [m for m in messages if not is_stale(m)]


class StaleHistoryFilter(AgentMiddleware):
    """Filtra, a cada chamada ao modelo, as respostas antigas indesejadas."""

    def __init__(self, markers: tuple[str, ...]):
        super().__init__()
        self.markers = markers

    def _clean(self, request):
        cleaned = drop_stale_messages(list(request.messages), self.markers)
        if len(cleaned) == len(request.messages):
            return request
        return request.override(messages=cleaned)

    def wrap_model_call(self, request, handler):
        return handler(self._clean(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._clean(request))


def create_stale_history_filter(markers: tuple[str, ...]) -> StaleHistoryFilter:
    """Cria o middleware para a lista `middleware=` do `create_agent()`."""
    return StaleHistoryFilter(markers)
