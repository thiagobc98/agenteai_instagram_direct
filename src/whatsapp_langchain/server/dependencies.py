"""FastAPI dependencies para validação e rate limiting.

Dependencies são injetadas automaticamente nas rotas via Depends().
Centralizar aqui mantém as rotas limpas e focadas na lógica de negócio.

Uso:
    from whatsapp_langchain.server.dependencies import check_rate_limit

    @router.post("/webhook/instagram")
    async def webhook(_valid: None = Depends(validate_instagram_signature)):
        ...
"""

import hashlib
import hmac
import time
import uuid

import structlog
from fastapi import HTTPException, Request

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.redis_client import get_redis

logger = structlog.get_logger()


def verify_instagram_signature(
    raw_body: bytes, signature_header: str | None, app_secret: str
) -> bool:
    """Confere o header X-Hub-Signature-256 contra o body bruto.

    A Meta assina o payload com HMAC-SHA256 usando o App Secret e envia o
    resultado como `sha256=<hex>`. Comparação em tempo constante evita
    timing attack.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


async def validate_instagram_signature(request: Request) -> None:
    """Valida a assinatura X-Hub-Signature-256 do webhook do Instagram.

    A Meta assina cada POST com o App Secret (INSTAGRAM_APP_SECRET); só quem
    conhece o segredo consegue gerar uma assinatura válida.

    Raises:
        HTTPException 403: Se a assinatura está ausente ou não confere.
        HTTPException 500: Se INSTAGRAM_APP_SECRET não está configurado.
    """
    app_secret = settings.instagram_app_secret
    if app_secret is None or not app_secret.get_secret_value():
        logger.error("instagram_app_secret_not_configured")
        raise HTTPException(
            status_code=500,
            detail="Instagram app secret not configured",
        )

    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_instagram_signature(
        raw_body, signature, app_secret.get_secret_value()
    ):
        logger.warning("instagram_signature_invalid")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")


async def check_rate_limit(external_id: str) -> None:
    """Verifica rate limit por remetente (IGSID).

    Usa sliding window de 1 hora em Redis (sorted set), compartilhado entre
    todas as réplicas da API. Remove entradas antigas e compara a
    quantidade de requisições com o limite configurado.

    Args:
        external_id: Identificador do remetente (IGSID do Instagram).

    Raises:
        HTTPException 429: Se o limite foi atingido.
    """
    redis = await get_redis()
    key = f"ratelimit:{external_id}"
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
            external_id=external_id,
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
