"""FastAPI application factory com lifespan.

Entry point do servidor HTTP. Configura logging, banco de dados,
CORS e inclui todos os routers.

Uso:
    uvicorn whatsapp_langchain.server.main:app --reload --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from whatsapp_langchain.agents.loader import AgentNotFoundError
from whatsapp_langchain.server.dependencies import require_admin_session
from whatsapp_langchain.server.routes.admin import router as admin_router
from whatsapp_langchain.server.routes.auth import router as auth_router
from whatsapp_langchain.server.routes.health import router as health_router
from whatsapp_langchain.server.routes.webhook_instagram import (
    router as webhook_instagram_router,
)
from whatsapp_langchain.server.routes.webhook_sync import (
    router as webhook_sync_router,
)
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import (
    bootstrap_langgraph_schema,
    close_pool,
    get_pool,
    run_migrations,
)
from whatsapp_langchain.shared.observability import setup_logging
from whatsapp_langchain.shared.redis_client import close_redis, get_redis

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gerencia o ciclo de vida da aplicação.

    Startup: configura logging, cria pool do banco, aplica migrações.
    Shutdown: fecha pool do banco.
    """
    # Startup
    setup_logging(
        log_level=settings.log_level,
        json_output=settings.log_json,
    )
    logger.info("server_starting", port=settings.port)

    pool = await get_pool()
    await run_migrations(pool)
    await bootstrap_langgraph_schema()
    await get_redis()
    logger.info("server_ready")

    yield

    # Shutdown
    await close_pool()
    await close_redis()
    logger.info("server_stopped")


app = FastAPI(
    title="Instagram Direct LangChain API",
    description="API para agentes conversacionais no Instagram Direct com LangGraph.",
    version="0.1.0",
    lifespan=lifespan,
)

# Sessão de admin (cookie assinado) — deve vir antes do CORS para que
# CORSMiddleware (adicionado por último) rode por fora na pilha.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key.get_secret_value(),
    same_site="lax",
    https_only=settings.session_cookie_secure,
    max_age=settings.session_max_age_seconds,
)

# CORS para o frontend (Next.js) — origem explícita, exigida pelo navegador
# quando allow_credentials=True (cookies de sessão).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(AgentNotFoundError)
async def agent_not_found_handler(
    request: Request, exc: AgentNotFoundError
) -> JSONResponse:
    """Retorna 400 quando o agent_id não existe no catálogo."""
    logger.warning("agent_not_found", agent_id=exc.agent_id)
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


# Routers
app.include_router(health_router)
app.include_router(webhook_instagram_router)
app.include_router(webhook_sync_router)
app.include_router(auth_router)
app.include_router(admin_router, dependencies=[Depends(require_admin_session)])
