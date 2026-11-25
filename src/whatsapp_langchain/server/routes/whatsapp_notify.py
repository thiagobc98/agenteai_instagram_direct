"""Tela "WhatsApp" do painel: conexão do Wuzapi e avisos para o atendente.

O número conectado aqui (QR Code) manda para o celular do atendente um aviso a
cada mensagem nova no Direct (ver `worker/notifier.py`).

"Conectar" faz tudo: cria a instância no Wuzapi se faltar (precisa de
WUZAPI_ADMIN_TOKEN) e liga a sessão. Depois o QR Code aparece no status até o
celular ler.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from whatsapp_langchain.server.dependencies import require_admin_session
from whatsapp_langchain.shared import attendant_notify as store
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.wuzapi_client import (
    WuzapiError,
    build_wuzapi_client,
    create_instance,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

NOT_CONFIGURED = "Preencha WUZAPI_API_URL e WUZAPI_TOKEN no .env"


def _settings_payload(config: store.NotifySettings) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "recipients": config.recipients,
        "updated_by": config.updated_by,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


async def connection_status() -> dict[str, Any]:
    """Situação da conexão para a tela, sem lançar erro."""
    result: dict[str, Any] = {
        "configured": False,
        "online": False,
        "instance_exists": False,
        "connected": False,
        "logged_in": False,
        "number": None,
        "qr_code": None,
        "can_create_instance": bool(settings.wuzapi_admin_token),
        "error": None,
    }
    wuzapi = build_wuzapi_client()
    if wuzapi is None:
        result["error"] = NOT_CONFIGURED
        return result
    result["configured"] = True

    try:
        session = await wuzapi.session_status()
    except WuzapiError as exc:
        result["online"] = True
        result["error"] = (
            "A instância ainda não existe no Wuzapi: clique em Conectar"
            if exc.status_code == 401
            else f"Wuzapi respondeu {exc.status_code}: {exc.detail}"
        )
        return result
    except httpx.HTTPError as exc:
        result["error"] = f"Wuzapi fora do ar ({type(exc).__name__})"
        return result

    result.update(online=True, instance_exists=True)
    result["connected"] = session["connected"]
    result["logged_in"] = session["logged_in"]
    result["number"] = session["jid"].split("@")[0].split(":")[0] or None

    if result["connected"] and not result["logged_in"]:
        try:
            result["qr_code"] = await wuzapi.qr_code() or None
        except (WuzapiError, httpx.HTTPError) as exc:
            logger.info("wuzapi_qr_unavailable", error=str(exc))
    return result


def _bad_gateway(exc: Exception) -> HTTPException:
    if isinstance(exc, WuzapiError):
        return HTTPException(status_code=502, detail=f"Wuzapi recusou: {exc.detail}")
    return HTTPException(status_code=502, detail="Wuzapi fora do ar")


@router.get("/status")
async def get_status() -> dict[str, Any]:
    pool = await get_pool()
    return {
        "connection": await connection_status(),
        "settings": _settings_payload(await store.get_settings(pool)),
    }


@router.post("/connect")
async def connect() -> dict[str, Any]:
    wuzapi = build_wuzapi_client()
    if wuzapi is None:
        raise HTTPException(status_code=400, detail=NOT_CONFIGURED)
    try:
        try:
            await wuzapi.session_status()
        except WuzapiError as exc:
            if exc.status_code != 401:
                raise
            if not settings.wuzapi_admin_token:
                raise HTTPException(
                    status_code=400,
                    detail="A instância não existe. Preencha WUZAPI_ADMIN_TOKEN no "
                    ".env para o painel criar sozinho.",
                ) from exc
            await create_instance(
                settings.wuzapi_api_url,
                settings.wuzapi_admin_token.get_secret_value(),
                wuzapi.token,
            )
        await wuzapi.connect()
    except (WuzapiError, httpx.HTTPError) as exc:
        logger.warning("wuzapi_connect_failed", error=str(exc))
        raise _bad_gateway(exc) from exc
    logger.info("wuzapi_connect_requested")
    return {"connection": await connection_status()}


@router.post("/disconnect")
async def disconnect() -> dict[str, Any]:
    wuzapi = build_wuzapi_client()
    if wuzapi is None:
        raise HTTPException(status_code=400, detail=NOT_CONFIGURED)
    try:
        await wuzapi.logout()
    except (WuzapiError, httpx.HTTPError) as exc:
        raise _bad_gateway(exc) from exc
    logger.info("wuzapi_disconnected_from_panel")
    return {"connection": await connection_status()}


class SettingsRequest(BaseModel):
    enabled: bool
    recipients: list[str] = Field(default_factory=list, max_length=5)


@router.put("/settings")
async def update_settings(
    body: SettingsRequest, admin: str = Depends(require_admin_session)
) -> dict[str, Any]:
    recipients, invalid = store.normalize_recipients(body.recipients)
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Número inválido: {', '.join(invalid)} (use DDD + número)",
        )
    if body.enabled and not recipients:
        raise HTTPException(
            status_code=422, detail="Cadastre pelo menos um celular para avisar"
        )
    pool = await get_pool()
    config = await store.save_settings(
        pool, enabled=body.enabled, recipients=recipients, updated_by=admin
    )
    logger.info("attendant_notify_settings_saved", recipients=len(recipients))
    return {"settings": _settings_payload(config)}


@router.post("/test")
async def send_test() -> dict[str, Any]:
    """Manda um aviso de teste para cada celular cadastrado."""
    wuzapi = build_wuzapi_client()
    if wuzapi is None:
        raise HTTPException(status_code=400, detail=NOT_CONFIGURED)
    pool = await get_pool()
    config = await store.get_settings(pool)
    if not config.recipients:
        raise HTTPException(status_code=422, detail="Nenhum celular cadastrado")

    text = (
        "✅ *Teste de aviso*\n\nDeu certo! A partir de agora você recebe aqui um "
        "aviso a cada mensagem nova no Direct do Instagram da loja."
    )
    results = []
    for phone in config.recipients:
        try:
            jid = await wuzapi.whatsapp_jid(phone)
            if jid is None:
                results.append({"phone": phone, "ok": False, "error": "sem WhatsApp"})
                continue
            await wuzapi.send_text(jid, text)
            results.append({"phone": phone, "ok": True, "error": None})
        except (WuzapiError, httpx.HTTPError) as exc:
            detail = exc.detail if isinstance(exc, WuzapiError) else "Wuzapi fora do ar"
            results.append({"phone": phone, "ok": False, "error": detail})
    return {"results": results}


@router.get("/notifications")
async def recent_notifications() -> dict[str, Any]:
    pool = await get_pool()
    return {"notifications": await store.list_recent(pool, limit=20)}
