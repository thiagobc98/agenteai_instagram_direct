"""Client Redis singleton para estado compartilhado entre réplicas.

Usado pelo rate limit distribuído (ver server/dependencies.py). O client é
criado no startup da aplicação (lifespan) e fechado no shutdown, seguindo o
mesmo padrão de shared/db.py.

Uso:
    from whatsapp_langchain.shared.redis_client import get_redis, close_redis

    # No lifespan da aplicação:
    redis = await get_redis()
    # ... app roda ...
    await close_redis()
"""

import structlog
from redis.asyncio import Redis

from whatsapp_langchain.shared.config import settings

logger = structlog.get_logger()

# Singleton do client Redis
_redis: Redis | None = None


async def get_redis() -> Redis:
    """Retorna o client Redis singleton, criando-o na primeira chamada.

    Returns:
        Client Redis assíncrono conectado a `settings.redis_url`.
    """
    global _redis

    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await _redis.ping()
        logger.info("redis_connected", url=settings.redis_url)

    return _redis


async def close_redis() -> None:
    """Fecha a conexão com o Redis, se existir."""
    global _redis

    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("redis_closed")
