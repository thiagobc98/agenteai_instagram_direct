"""Rotas do painel para criar e agendar publicações (Feed, Story, Reels).

Fluxo: criar rascunho -> subir mídia -> (opcional) gerar legenda com IA ->
editar -> agendar/publicar agora. Quem publica é o Worker
(`worker/publisher.py`), no horário agendado.

Uso:
    curl -X POST localhost:8000/api/publications -d '{"kind": "feed"}'
    curl -X POST localhost:8000/api/publications/1/media -F file=@foto.jpg
    curl -X POST localhost:8000/api/publications/1/caption
    curl -X POST localhost:8000/api/publications/1/schedule -d '{"publish_at": null}'
"""

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from whatsapp_langchain.agents.captions import describe_image, generate_caption
from whatsapp_langchain.server.dependencies import require_admin_session
from whatsapp_langchain.shared import publishing as store
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.db import get_pool
from whatsapp_langchain.shared.media_storage import (
    MediaRejectedError,
    delete_media_file,
    public_base_url_problem,
    read_media,
    store_media,
)
from whatsapp_langchain.worker.instagram_client import (
    InstagramClient,
    InstagramSendError,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["publishing"])

# Agendamento máximo à frente (o container da Meta é criado só na hora).
MAX_SCHEDULE_AHEAD = timedelta(days=75)


async def _load(pub_id: int) -> dict:
    pool = await get_pool()
    pub = await store.get_publication(pool, pub_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Publicação não encontrada")
    return pub


def _with_validation(pub: dict) -> dict:
    v = store.validate_publication(
        pub["kind"], pub["caption"], store.media_info(pub["media"])
    )
    problem = public_base_url_problem()
    pub["validation"] = {
        "errors": v.errors,
        "warnings": v.warnings,
        "public_url_problem": problem,
    }
    return pub


def _require_editable(pub: dict) -> None:
    if pub["status"] not in store.EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Só dá para editar rascunho ou publicação com falha. "
            "Se estiver agendada, volte para rascunho antes.",
        )


@router.get("/publications")
async def list_publications(limit: int = Query(default=100, ge=1, le=300)) -> dict:
    pool = await get_pool()
    return {"publications": await store.list_publications(pool, limit=limit)}


@router.get("/publications/quota")
async def publishing_quota() -> dict:
    """Cota de publicações via API (100 a cada 24h) e se a URL pública está ok."""
    token = settings.instagram_access_token
    quota = None
    if token and token.get_secret_value():
        client = InstagramClient(
            token.get_secret_value(),
            settings.instagram_graph_api_version,
            settings.instagram_graph_base_url,
        )
        try:
            account = await client.get_account()
            ig_user_id = str(account.get("user_id") or account.get("id") or "")
            if ig_user_id:
                quota = await client.publishing_quota(ig_user_id)
        except InstagramSendError as exc:
            logger.warning("publishing_quota_failed", error=str(exc))
    return {
        "quota_usage": quota[0] if quota else None,
        "quota_total": quota[1] if quota else None,
        "public_url_problem": public_base_url_problem(),
    }


class CreateRequest(BaseModel):
    kind: str = Field(pattern="^(feed|story|reels)$")


@router.post("/publications")
async def create_publication(
    body: CreateRequest, admin: str = Depends(require_admin_session)
) -> dict:
    pool = await get_pool()
    pub_id = await store.create_publication(pool, kind=body.kind, created_by=admin)
    return {"publication": _with_validation(await _load(pub_id))}


@router.get("/publications/{pub_id}")
async def get_publication(pub_id: int) -> dict:
    return {"publication": _with_validation(await _load(pub_id))}


class UpdateRequest(BaseModel):
    kind: str | None = Field(default=None, pattern="^(feed|story|reels)$")
    brief: str | None = Field(default=None, max_length=4000)
    caption: str | None = Field(default=None, max_length=5000)
    share_to_feed: bool | None = None


@router.patch("/publications/{pub_id}")
async def update_publication(pub_id: int, body: UpdateRequest) -> dict:
    _require_editable(await _load(pub_id))
    pool = await get_pool()
    await store.update_draft(
        pool,
        pub_id,
        kind=body.kind,
        brief=body.brief,
        caption=body.caption,
        share_to_feed=body.share_to_feed,
    )
    return {"publication": _with_validation(await _load(pub_id))}


@router.post("/publications/{pub_id}/media")
async def upload_media(
    pub_id: int,
    file: UploadFile = File(...),
    # Vídeo: o navegador lê duração e dimensões (o servidor não decodifica vídeo)
    duration_seconds: float | None = Form(default=None),
    width: int | None = Form(default=None),
    height: int | None = Form(default=None),
) -> dict:
    pub = await _load(pub_id)
    _require_editable(pub)
    if len(pub["media"]) >= store.MAX_CAROUSEL_ITEMS:
        raise HTTPException(
            status_code=422, detail="Máximo de 10 mídias por publicação."
        )

    try:
        # Pillow e escrita de vídeo grande são bloqueantes: fora do event loop
        stored = await run_in_threadpool(store_media, file.file, file.content_type)
    except MediaRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()

    is_video = stored.media_kind == "video"
    pool = await get_pool()
    await store.add_media(
        pool,
        pub_id,
        token=stored.token,
        media_kind=stored.media_kind,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        width=width if is_video else stored.width,
        height=height if is_video else stored.height,
        duration_seconds=duration_seconds if is_video else None,
        original_name=(file.filename or "")[:200] or None,
    )
    logger.info(
        "publication_media_uploaded",
        pub_id=pub_id,
        media_kind=stored.media_kind,
        size_bytes=stored.size_bytes,
    )
    return {"publication": _with_validation(await _load(pub_id))}


@router.delete("/publications/{pub_id}/media/{media_id}")
async def remove_media(pub_id: int, media_id: int) -> dict:
    _require_editable(await _load(pub_id))
    pool = await get_pool()
    token = await store.delete_media(pool, pub_id, media_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Mídia não encontrada")
    delete_media_file(token)
    return {"publication": _with_validation(await _load(pub_id))}


class ReorderRequest(BaseModel):
    media_ids: list[int]


@router.put("/publications/{pub_id}/media/order")
async def reorder_media(pub_id: int, body: ReorderRequest) -> dict:
    pub = await _load(pub_id)
    _require_editable(pub)
    if sorted(body.media_ids) != sorted(m["id"] for m in pub["media"]):
        raise HTTPException(status_code=422, detail="Lista de mídias não confere")
    pool = await get_pool()
    await store.reorder_media(pool, pub_id, body.media_ids)
    return {"publication": _with_validation(await _load(pub_id))}


@router.post("/publications/{pub_id}/caption")
async def ai_caption(pub_id: int) -> dict:
    """Gera a legenda com IA (descreve as fotos e escreve a partir do briefing).

    A legenda gerada substitui o campo de legenda (a anterior fica no
    histórico do navegador, via desfazer) e é guardada em `ai_caption`.
    """
    pub = await _load(pub_id)
    _require_editable(pub)
    if pub["kind"] == "story":
        raise HTTPException(status_code=422, detail="Story não tem legenda.")
    if not pub["media"] and not pub["brief"].strip():
        raise HTTPException(
            status_code=422, detail="Suba a mídia ou escreva um briefing antes."
        )

    pool = await get_pool()
    descriptions: list[str] = []
    for m in pub["media"]:
        if m["media_kind"] != "image":
            continue
        description = m["ai_description"]
        if not description:
            data = await run_in_threadpool(read_media, m["token"])
            if data is None:
                continue
            try:
                description = await describe_image(data, m["content_type"])
            except Exception as exc:
                # Sem descrição a legenda sai só do briefing: não bloqueia.
                logger.warning(
                    "caption_describe_failed", media_id=m["id"], error=str(exc)
                )
                continue
            await store.set_media_description(pool, m["id"], description)
        descriptions.append(description)

    try:
        draft = await generate_caption(
            kind=pub["kind"],
            brief=pub["brief"],
            media_descriptions=descriptions,
            media_count=len(pub["media"]),
            has_video=any(m["media_kind"] == "video" for m in pub["media"]),
        )
    except Exception as exc:
        logger.error("caption_generation_failed", pub_id=pub_id, error=str(exc))
        raise HTTPException(status_code=502, detail=_llm_error_message(exc)) from exc

    await store.update_draft(
        pool, pub_id, caption=draft.full_text, ai_caption=draft.full_text
    )
    result = _with_validation(await _load(pub_id))
    return {"publication": result, "notes": draft.notes}


def _llm_error_message(exc: Exception) -> str:
    """Mensagem para o painel; o detalhe técnico fica no log."""
    text = str(exc)
    if "401" in text or "User not found" in text:
        return (
            "A IA está indisponível: a chave do OpenRouter "
            "(OPENROUTER_API_KEY) foi recusada."
        )
    if "402" in text:
        return "A IA está indisponível: sem créditos no OpenRouter."
    if "429" in text:
        return "A IA está sobrecarregada agora. Tente de novo em instantes."
    if isinstance(exc, ValueError):
        return "A IA devolveu uma resposta fora do formato. Tente gerar de novo."
    return "A IA não conseguiu gerar a legenda agora. Tente de novo ou escreva à mão."


class ScheduleRequest(BaseModel):
    # None = publicar agora
    publish_at: datetime | None = None


@router.post("/publications/{pub_id}/schedule")
async def schedule_publication(
    pub_id: int, body: ScheduleRequest, admin: str = Depends(require_admin_session)
) -> dict:
    """Aprova a publicação: o Worker publica em `publish_at` (ou já)."""
    pub = _with_validation(await _load(pub_id))
    _require_editable(pub)

    problems = list(pub["validation"]["errors"])
    if pub["validation"]["public_url_problem"]:
        problems.append(pub["validation"]["public_url_problem"])
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))

    now = datetime.now(UTC)
    publish_at = body.publish_at or now
    if publish_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Informe o horário com fuso.")
    if publish_at < now - timedelta(minutes=1):
        raise HTTPException(status_code=422, detail="O horário já passou.")
    if publish_at > now + MAX_SCHEDULE_AHEAD:
        raise HTTPException(
            status_code=422, detail="Agende no máximo 75 dias à frente."
        )

    pool = await get_pool()
    if not await store.schedule(pool, pub_id, publish_at=publish_at, approved_by=admin):
        raise HTTPException(
            status_code=409, detail="A publicação mudou de estado. Recarregue."
        )
    logger.info(
        "publication_scheduled",
        pub_id=pub_id,
        kind=pub["kind"],
        publish_at=publish_at.isoformat(),
        approved_by=admin,
    )
    return {"publication": _with_validation(await _load(pub_id))}


@router.post("/publications/{pub_id}/unschedule")
async def unschedule_publication(pub_id: int) -> dict:
    pool = await get_pool()
    if not await store.unschedule(pool, pub_id):
        raise HTTPException(
            status_code=409,
            detail="Não dá para voltar para rascunho: a publicação já começou a subir.",
        )
    return {"publication": _with_validation(await _load(pub_id))}


@router.delete("/publications/{pub_id}")
async def cancel_publication(pub_id: int) -> dict:
    pool = await get_pool()
    tokens = await store.cancel(pool, pub_id)
    if tokens is None:
        raise HTTPException(
            status_code=409,
            detail="Não dá para descartar: já publicada ou subindo agora.",
        )
    for token in tokens:
        delete_media_file(token)
    return {"ok": True}
