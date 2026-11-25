"""Rotas da tela "Facebook" do painel: situação da Página e sincronização.

Listar, aprovar e ignorar comentários usam as rotas comuns de
`routes/comments.py` com `?channel=facebook`.

Uso:
    curl http://localhost:8000/api/facebook/status
    curl -X POST http://localhost:8000/api/facebook/sync
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query

from whatsapp_langchain.server.routes.comments import (
    PENDING_STATUSES,
    PRIVATE_REPLY_WINDOW,
    facebook_client_or_503,
    facebook_error,
)
from whatsapp_langchain.shared import comments as store
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.facebook_comments_payload import MAX_COMMENT_TEXT
from whatsapp_langchain.worker.facebook_client import (
    FacebookGraphError,
    build_facebook_client,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/facebook", tags=["facebook"])


def _missing_settings() -> list[str]:
    """Variáveis que faltam para a integração completa (sem revelar valores)."""
    missing = []
    if not settings.facebook_page_id:
        missing.append("FACEBOOK_PAGE_ID")
    token = settings.facebook_page_access_token
    if token is None or not token.get_secret_value():
        missing.append("FACEBOOK_PAGE_ACCESS_TOKEN")
    secret = settings.facebook_app_secret
    if secret is None or not secret.get_secret_value():
        missing.append("FACEBOOK_APP_SECRET")
    return missing


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Situação da integração com a Página, sem lançar erro.

    Confere o token com `GET /me`: ele precisa ser da MESMA Página do
    FACEBOOK_PAGE_ID (um token de usuário ou de outra Página responderia em
    nome errado).
    """
    pool = await get_pool()
    counts = await store.comment_counts(pool, channel=store.FACEBOOK)
    result: dict[str, Any] = {
        "configured": False,
        "missing": _missing_settings(),
        "page": None,
        "error": None,
        "pending_total": sum(counts.get(s, 0) for s in PENDING_STATUSES),
    }
    facebook = build_facebook_client()
    if facebook is None:
        result["error"] = "Página do Facebook não configurada no .env"
        return result
    result["configured"] = True

    try:
        page = await facebook.get_page()
    except FacebookGraphError as exc:
        result["error"] = facebook_error(exc).detail
        return result
    except httpx.HTTPError as exc:
        result["error"] = f"Facebook fora do ar ({type(exc).__name__})"
        return result

    result["page"] = {"id": page.get("id"), "name": page.get("name")}
    if str(page.get("id")) != settings.facebook_page_id:
        result["error"] = (
            "O token não é da Página configurada em FACEBOOK_PAGE_ID. "
            "Gere um token da Página (Page Access Token), não de usuário."
        )
    return result


def _parse_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("+0000", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


@router.post("/sync")
async def sync(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    """Busca os posts recentes da Página e os comentários deles.

    Mesmas regras do Instagram: comentários dos últimos 7 dias, sem resposta
    da Página, entram como `new` (a IA rascunha); os outros como `archived`
    (só consulta). Comentários já conhecidos não são alterados.
    """
    facebook = facebook_client_or_503()
    pool = await get_pool()
    page_id = settings.facebook_page_id

    try:
        posts = await facebook.list_posts(limit=limit)
    except FacebookGraphError as exc:
        raise facebook_error(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Facebook fora do ar") from exc

    now = datetime.now(UTC)
    new_comments = failed_posts = 0
    for post in posts:
        await store.upsert_post(pool, post, channel=store.FACEBOOK)
        if not post.get("comments_count"):
            continue
        try:
            items = await facebook.list_comments(post["id"])
        except (FacebookGraphError, httpx.HTTPError) as exc:
            failed_posts += 1
            logger.warning(
                "facebook_sync_post_failed", post_id=post["id"], error=str(exc)
            )
            continue

        def sender_id(item: dict) -> str:
            sender = item.get("from") if isinstance(item.get("from"), dict) else {}
            return str(sender.get("id") or "")

        # Comentários que a Página já respondeu não precisam de rascunho
        answered = {
            (item.get("parent") or {}).get("id")
            for item in items
            if sender_id(item) == page_id
        }

        for item in items:
            sender = item.get("from") if isinstance(item.get("from"), dict) else {}
            commented_at = _parse_time(item.get("created_time"))
            if sender_id(item) == page_id:
                status = "ignored"
            elif item["id"] in answered or now - commented_at > PRIVATE_REPLY_WINDOW:
                status = "archived"
            else:
                status = "new"
            parent = (item.get("parent") or {}).get("id")
            created = await store.insert_comment(
                pool,
                comment_id=str(item["id"]),
                media_id=str(post["id"]),
                text=str(item.get("message") or "")[:MAX_COMMENT_TEXT],
                from_id=sender_id(item) or None,
                from_username=(str(sender.get("name") or "").strip() or None),
                parent_id=str(parent) if parent else None,
                commented_at=commented_at,
                status=status,
                channel=store.FACEBOOK,
            )
            new_comments += int(created and status == "new")

    logger.info(
        "facebook_sync_done",
        posts=len(posts),
        new_comments=new_comments,
        failed_posts=failed_posts,
    )
    return {
        "posts": len(posts),
        "new_comments": new_comments,
        "failed_posts": failed_posts,
    }
