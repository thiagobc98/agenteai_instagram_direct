"""Rotas do painel para o agente de marketing (tela Marketing).

Uso:
    curl -X POST localhost:8000/api/marketing/threads
    curl -X POST localhost:8000/api/marketing/threads/1/messages \
         -d '{"content": "Monte o plano de conteúdo da próxima semana"}'
"""

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from whatsapp_langchain.agents.marketing import MarketingContext, run_turn
from whatsapp_langchain.server.dependencies import require_admin_session
from whatsapp_langchain.shared import marketing as store
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.worker.instagram_client import InstagramClient

logger = structlog.get_logger()

router = APIRouter(prefix="/api/marketing", tags=["marketing"])

# Uma pergunta por vez em cada conversa (evita respostas cruzadas e custo dobrado)
_locks: dict[int, asyncio.Lock] = {}


def _lock(thread_id: int) -> asyncio.Lock:
    return _locks.setdefault(thread_id, asyncio.Lock())


def _instagram() -> InstagramClient | None:
    token = settings.instagram_access_token
    if token is None or not token.get_secret_value():
        return None
    return InstagramClient(
        token.get_secret_value(),
        settings.instagram_graph_api_version,
        settings.instagram_graph_base_url,
    )


def _error_message(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, TimeoutError):
        return (
            "A análise demorou demais e foi interrompida. "
            "Tente uma pergunta mais específica."
        )
    if "401" in text or "User not found" in text:
        return (
            "A IA está indisponível: a chave do OpenRouter "
            "(OPENROUTER_API_KEY) foi recusada."
        )
    if "402" in text:
        return "A IA está indisponível: sem créditos no OpenRouter."
    if "429" in text:
        return "A IA está sobrecarregada agora. Tente de novo em instantes."
    if "recursion" in text.lower():
        return "A análise ficou longa demais. Tente dividir a pergunta em partes."
    return "Não consegui responder agora. Tente de novo em instantes."


def _history(messages: list[dict]) -> list[dict]:
    """Só trocas válidas vão para o modelo (respostas de erro ficam de fora)."""
    return [
        m
        for m in messages
        if not any(a.get("type") == "error" for a in m.get("actions") or [])
    ]


@router.get("/threads")
async def list_threads() -> dict:
    pool = await get_pool()
    return {"threads": await store.list_threads(pool)}


class CreateThread(BaseModel):
    title: str = Field(default="Nova conversa", max_length=120)


@router.post("/threads")
async def create_thread(
    body: CreateThread | None = None, admin: str = Depends(require_admin_session)
) -> dict:
    pool = await get_pool()
    title = body.title if body else "Nova conversa"
    return {"thread": await store.create_thread(pool, title=title, created_by=admin)}


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: int) -> dict:
    pool = await get_pool()
    thread = await store.get_thread(pool, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    return {
        "thread": thread,
        "messages": await store.list_messages(pool, thread_id),
        "busy": _lock(thread_id).locked(),
    }


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: int) -> dict:
    pool = await get_pool()
    if not await store.delete_thread(pool, thread_id):
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    _locks.pop(thread_id, None)
    return {"ok": True}


class Ask(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@router.post("/threads/{thread_id}/messages")
async def ask(
    thread_id: int, body: Ask, admin: str = Depends(require_admin_session)
) -> dict:
    """Envia uma pergunta ao agente e devolve a resposta (pode levar ~1 min)."""
    pool = await get_pool()
    thread = await store.get_thread(pool, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    lock = _lock(thread_id)
    if lock.locked():
        raise HTTPException(
            status_code=409, detail="O agente ainda está respondendo esta conversa."
        )

    async with lock:
        previous = await store.list_messages(pool, thread_id, limit=40)
        question = body.content.strip()
        user_msg = await store.add_message(
            pool, thread_id, role="user", content=question, created_by=admin
        )
        if not previous and thread["title"] == "Nova conversa":
            await _rename(pool, thread_id, question)

        ctx = MarketingContext(pool=pool, instagram=_instagram(), created_by=admin)
        try:
            result = await run_turn(ctx, _history(previous), question)
        except Exception as exc:
            logger.error("marketing_turn_failed", thread_id=thread_id, error=str(exc))
            # Rascunhos criados antes da falha continuam valendo: mostra no painel
            reply = await store.add_message(
                pool,
                thread_id,
                role="assistant",
                content=_error_message(exc),
                actions=[*ctx.actions, {"type": "error"}],
            )
            return {"messages": [user_msg, reply]}

        actions = list(ctx.actions)
        if result.tools_used:
            actions.append({"type": "tools", "names": result.tools_used})
        reply = await store.add_message(
            pool, thread_id, role="assistant", content=result.reply, actions=actions
        )
        logger.info(
            "marketing_turn_done",
            thread_id=thread_id,
            tools=result.tools_used,
            drafts=ctx.drafts_created,
        )
        return {"messages": [user_msg, reply]}


async def _rename(pool, thread_id: int, question: str) -> None:
    title = question.split("\n")[0][:60] + ("..." if len(question) > 60 else "")
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE marketing_threads SET title = %s WHERE id = %s", (title, thread_id)
        )
        await conn.commit()
