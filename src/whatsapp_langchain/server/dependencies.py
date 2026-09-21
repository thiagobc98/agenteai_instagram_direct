"""FastAPI dependencies para validação e rate limiting.

Dependencies são injetadas automaticamente nas rotas via Depends().
Centralizar aqui mantém as rotas limpas e focadas na lógica de negócio.

Uso:
    from whatsapp_langchain.server.dependencies import check_rate_limit

    @router.post("/webhook/evolution/{token}")
    async def webhook(rate_limit: None = Depends(check_rate_limit)):
        ...
"""

import hmac
import time
import uuid

import structlog
from fastapi import HTTPException, Request

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.redis_client import get_redis

logger = structlog.get_logger()


async def validate_evolution_webhook_token(token: str) -> None:
    """Valida o token secreto do path `/webhook/evolution/{token}`.

    O Evolution API não assina os webhooks (sem equivalente ao
    X-Twilio-Signature do Twilio) — a proteção aqui é um token compartilhado
    próprio (EVOLUTION_WEBHOOK_TOKEN), incluído na URL configurada no
    Evolution Manager. Comparação em tempo constante evita timing attack.

    Raises:
        HTTPException 403: Se o token não confere.
        HTTPException 500: Se EVOLUTION_WEBHOOK_TOKEN não está configurado.
    """
    if not settings.evolution_webhook_token:
        logger.error("evolution_webhook_token_not_configured")
        raise HTTPException(
            status_code=500,
            detail="Evolution webhook token not configured",
        )

    if not hmac.compare_digest(token, settings.evolution_webhook_token):
        logger.warning("evolution_webhook_token_invalid")
        raise HTTPException(status_code=403, detail="Invalid webhook token")


async def check_rate_limit(phone_number: str) -> None:
    """Verifica rate limit por número de telefone.

    Usa sliding window de 1 hora em Redis (sorted set), compartilhado entre
    todas as réplicas da API. Remove entradas antigas e compara a
    quantidade de requisições com o limite configurado.

    Args:
        phone_number: Número de telefone do remetente.

    Raises:
        HTTPException 429: Se o limite foi atingido.
    """
    redis = await get_redis()
    key = f"ratelimit:{phone_number}"
    now = time.time()
    one_hour_ago = now - 3600

    async with redis.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, 0, one_hour_ago)
        pipe.zcard(key)
        results = await pipe.execute()
    count = results[1]

    if count >= settings.rate_limit_per_hour:
        logger.warning(
            "rate_limit_exceeded",
            phone=phone_number,
            count=count,
            limit=settings.rate_limit_per_hour,
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
        )

    async with redis.pipeline(transaction=True) as pipe:
        pipe.zadd(key, {str(uuid.uuid4()): now})
        pipe.expire(key, 3600)
        await pipe.execute()


async def require_admin_session(request: Request) -> str:
    """Exige sessão de admin autenticada via cookie assinado.

    Usado como dependency das rotas administrativas (`/api/*`).

    Args:
        request: Request HTTP do FastAPI.

    Returns:
        Username do admin autenticado.

    Raises:
        HTTPException 401: Se não há sessão válida.
    """
    admin_username = request.session.get("admin_username")
    if not admin_username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return admin_username
