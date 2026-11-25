"""Helpers internos para extrair contexto de execução (runtime) das tools.

O worker injeta `user_id` (IGSID do remetente no Instagram) e `thread_id` via
`configurable` em cada chamada ao grafo — ver worker/processor.py. Tools que
precisam identificar o remetente atual (memória, agendamento, etc.) resolvem
esse valor por aqui.
"""

from typing import Any

from langchain_core.runnables.config import var_child_runnable_config


def extract_configurable(runtime: Any) -> dict:
    """Extrai o dict `configurable` do contexto de execução da tool."""
    if runtime is not None:
        config = getattr(runtime, "config", None)
        if isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                return configurable

    cfg = var_child_runnable_config.get(None)
    if isinstance(cfg, dict):
        configurable = cfg.get("configurable", {})
        if isinstance(configurable, dict):
            return configurable

    return {}


def extract_user_id(runtime: Any) -> tuple[str | None, str | None]:
    """Resolve o ID do remetente atual (`user_id`) a partir do runtime.

    Returns:
        (user_id, error) — error é None quando user_id foi encontrado.
    """
    configurable = extract_configurable(runtime)
    user_id = configurable.get("user_id")
    if not user_id:
        return None, "user_id não encontrado na configuração."
    return str(user_id), None
