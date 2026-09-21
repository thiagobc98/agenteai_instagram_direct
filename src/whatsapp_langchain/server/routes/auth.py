"""Rotas de autenticação do admin panel.

Login simples via usuário/senha configurados em env, com sessão mantida
em cookie assinado (SessionMiddleware). Usado pelo frontend (Next.js
Admin Panel) para autenticar antes de acessar as rotas `/api/*`.

Uso:
    curl -X POST http://localhost:8000/api/auth/login \
        -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"..."}'
    curl http://localhost:8000/api/auth/me
    curl -X POST http://localhost:8000/api/auth/logout
"""

import hmac

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from whatsapp_langchain.server.dependencies import require_admin_session
from whatsapp_langchain.shared.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    username: str


@router.post("/login", response_model=AuthResponse)
async def login(request: Request, credentials: LoginRequest) -> AuthResponse:
    """Autentica o admin e cria a sessão.

    Raises:
        HTTPException 401: Se usuário/senha não conferem ou não estão
            configurados.
    """
    configured_password = (
        settings.admin_password.get_secret_value() if settings.admin_password else ""
    )

    valid_username = hmac.compare_digest(credentials.username, settings.admin_username)
    valid_password = bool(configured_password) and hmac.compare_digest(
        credentials.password, configured_password
    )

    if not (valid_username and valid_password):
        logger.warning("admin_login_failed", username=credentials.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    request.session["admin_username"] = settings.admin_username
    logger.info("admin_login_success", username=settings.admin_username)
    return AuthResponse(username=settings.admin_username)


@router.post("/logout")
async def logout(request: Request) -> dict[str, bool]:
    """Encerra a sessão do admin."""
    request.session.clear()
    return {"ok": True}


@router.get("/me", response_model=AuthResponse)
async def me(admin_username: str = Depends(require_admin_session)) -> AuthResponse:
    """Retorna o usuário autenticado na sessão atual.

    Raises:
        HTTPException 401: Se não há sessão válida.
    """
    return AuthResponse(username=admin_username)
