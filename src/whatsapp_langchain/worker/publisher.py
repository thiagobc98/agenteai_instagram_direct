"""Worker: publica no Instagram as publicações aprovadas no painel.

Máquina de estados (uma etapa por chamada, sem bloquear o loop do Worker
enquanto a Meta processa vídeo):

    scheduled ──cria container(s)──► processing ──FINISHED──► publishing ──► published
        ▲                               │ IN_PROGRESS: confere de novo em 15s
        └──── cota diária / falha ──────┤ ERROR: failed
              transitória (adiado)      └ EXPIRED: recria o container

Idempotência: `media_publish` repetido publicaria em dobro. Por isso, antes
de (re)tentar publicar, o Worker consulta o container: se a Meta já marcou
PUBLISHED, só registra como publicado.

Referência: Instagram Content Publishing API
(POST /{ig-user-id}/media, GET /{container}?fields=status_code,
POST /{ig-user-id}/media_publish).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.shared import publishing as store
from whatsapp_langchain.shared.media_storage import public_base_url_problem, public_url
from whatsapp_langchain.worker.instagram_client import (
    InstagramClient,
    InstagramSendError,
)

logger = structlog.get_logger()

LEASE_SECONDS = 120
CHECK_IMAGE_SECONDS = 3
CHECK_VIDEO_SECONDS = 15
# A Meta expira containers não publicados em 24h.
CONTAINER_MAX_AGE = timedelta(hours=23)
# Vídeo que não termina de processar nesse tempo: desiste com erro.
PROCESSING_TIMEOUT = timedelta(minutes=30)
# Cota diária esgotada: tenta de novo em 1h.
QUOTA_RETRY_SECONDS = 3600
# Falhas transitórias (rede, 5xx, rate limit) antes de desistir.
MAX_TRANSIENT_ATTEMPTS = 5

_ig_user_id: str | None = None


async def _account_id(instagram: InstagramClient) -> str:
    """ID da conta profissional (cacheado: não muda)."""
    global _ig_user_id
    if _ig_user_id is None:
        account = await instagram.get_account()
        _ig_user_id = str(account.get("user_id") or account.get("id") or "")
        if not _ig_user_id:
            raise InstagramSendError(200, "Não foi possível obter o ID da conta (/me)")
    return _ig_user_id


def is_transient(exc: Exception) -> bool:
    """Erro que vale tentar de novo (rede, 5xx, rate limit)."""
    if isinstance(exc, InstagramSendError):
        if exc.is_token_invalid:
            return False
        return exc.is_rate_limited or exc.status_code >= 500
    return True  # timeout / conexão


def describe_error(exc: Exception) -> str:
    if isinstance(exc, InstagramSendError):
        if exc.is_token_invalid:
            return "Token do Instagram inválido ou expirado. Gere um novo e reagende."
        if exc.code in (10, 200):
            return (
                "O token não tem permissão para publicar "
                "(instagram_business_content_publish)."
            )
        return f"Instagram recusou: {exc.detail}"
    return f"Erro de rede: {exc}"


def build_container_params(pub: dict) -> tuple[list[dict], dict | None]:
    """Parâmetros dos containers: (itens do carrossel, container principal).

    Para carrossel o container principal depende dos IDs dos itens, então
    volta `None` e é montado por `carousel_params` depois de criar os itens.
    """
    media = pub["media"]
    kind = pub["kind"]

    def source(m: dict) -> dict:
        key = "video_url" if m["media_kind"] == "video" else "image_url"
        return {key: public_url(m["token"])}

    if kind == "story":
        return [], {"media_type": "STORIES", **source(media[0])}

    if kind == "reels":
        return [], {
            "media_type": "REELS",
            **source(media[0]),
            "caption": pub["caption"],
            "share_to_feed": bool(pub["share_to_feed"]),
        }

    if len(media) == 1:
        return [], {**source(media[0]), "caption": pub["caption"]}

    children = []
    for m in media:
        item = {**source(m), "is_carousel_item": True}
        if m["media_kind"] == "video":
            item["media_type"] = "VIDEO"
        children.append(item)
    return children, None


def carousel_params(pub: dict, child_ids: list[str]) -> dict:
    return {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": pub["caption"],
    }


def _has_video(pub: dict) -> bool:
    return any(m["media_kind"] == "video" for m in pub["media"])


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


async def _fail_or_postpone(
    pool: AsyncConnectionPool, pub: dict, exc: Exception
) -> None:
    reason = describe_error(exc)
    if is_transient(exc) and pub["attempts"] + 1 < MAX_TRANSIENT_ATTEMPTS:
        delay = 60 * 2 ** pub["attempts"]
        logger.warning(
            "publication_postponed", pub_id=pub["id"], delay=delay, error=reason
        )
        await store.postpone(
            pool, pub["id"], delay, f"Nova tentativa em breve: {reason}"
        )
    else:
        logger.error("publication_failed", pub_id=pub["id"], error=reason)
        await store.mark_failed(pool, pub["id"], reason)


async def _create_containers(
    pool: AsyncConnectionPool, instagram: InstagramClient, pub: dict, ig_user_id: str
) -> None:
    """scheduled -> processing (ou continua scheduled esperando itens de vídeo)."""
    problem = public_base_url_problem()
    if problem:
        await store.mark_failed(pool, pub["id"], problem)
        return

    validation = store.validate_publication(
        pub["kind"], pub["caption"], store.media_info(pub["media"])
    )
    if not validation.ok:
        await store.mark_failed(pool, pub["id"], " ".join(validation.errors))
        return

    quota = await instagram.publishing_quota(ig_user_id)
    if quota and quota[0] >= quota[1]:
        await store.postpone(
            pool,
            pub["id"],
            QUOTA_RETRY_SECONDS,
            f"Cota diária da Meta atingida ({quota[0]}/{quota[1]} publicações em 24h). "
            "Nova tentativa em 1h.",
        )
        return

    children, params = build_container_params(pub)

    if children:
        child_ids: list[str] = []
        pending_video = False
        for m, child in zip(pub["media"], children, strict=True):
            container_id = m["container_id"]
            if not container_id:
                container_id = await instagram.create_container(ig_user_id, child)
                await store.set_child_container(pool, m["id"], container_id)
            if m["media_kind"] == "video":
                status, message = await instagram.container_status(container_id)
                if status == "ERROR":
                    await store.mark_failed(
                        pool,
                        pub["id"],
                        f"A Meta não aceitou um vídeo do carrossel: {message}",
                    )
                    return
                pending_video |= status != "FINISHED"
            child_ids.append(container_id)
        if pending_video:
            # Itens de vídeo ainda processando: confere de novo (continua scheduled)
            await store.check_again_in(pool, pub["id"], CHECK_VIDEO_SECONDS)
            return
        params = carousel_params(pub, child_ids)

    container_id = await instagram.create_container(ig_user_id, params)
    wait = CHECK_VIDEO_SECONDS if _has_video(pub) else CHECK_IMAGE_SECONDS
    await store.set_processing(pool, pub["id"], container_id, wait)


async def _find_published_media(
    instagram: InstagramClient, pub: dict
) -> tuple[str | None, str | None]:
    """Container já PUBLISHED sem o ID salvo: procura a mídia pelas recentes."""
    if pub["kind"] == "story":
        return None, None
    try:
        for item in await instagram.list_media(limit=10):
            if (item.get("caption") or "") == pub["caption"]:
                return item.get("id"), item.get("permalink")
    except Exception:
        pass
    return None, None


async def _publish(
    pool: AsyncConnectionPool, instagram: InstagramClient, pub: dict, ig_user_id: str
) -> None:
    """processing/publishing -> published (quando a Meta terminou de processar)."""
    container_id = pub["container_id"]
    created = _parse(pub["container_created_at"])
    now = datetime.now(UTC)

    status, message = await instagram.container_status(container_id)

    if status == "PUBLISHED":
        media_id, permalink = await _find_published_media(instagram, pub)
        await store.mark_published(
            pool, pub["id"], ig_media_id=media_id, permalink=permalink
        )
        logger.info("publication_already_published", pub_id=pub["id"])
        return

    if status == "EXPIRED" or (created and now - created > CONTAINER_MAX_AGE):
        await store.postpone(
            pool, pub["id"], 0, "Container expirou na Meta: recriando."
        )
        return

    if status == "ERROR":
        await store.mark_failed(
            pool,
            pub["id"],
            f"A Meta não conseguiu processar a mídia: {message or 'erro sem detalhe'}. "
            "Confira formato, duração e proporção.",
        )
        return

    if status != "FINISHED":
        if created and now - created > PROCESSING_TIMEOUT:
            await store.mark_failed(
                pool,
                pub["id"],
                "A Meta não terminou de processar a mídia em 30 minutos.",
            )
        else:
            await store.check_again_in(pool, pub["id"], CHECK_VIDEO_SECONDS)
        return

    await store.set_publishing(pool, pub["id"], LEASE_SECONDS)
    media_id = await instagram.publish_container(ig_user_id, container_id)

    permalink = None
    try:
        permalink = (await instagram.get_media(media_id)).get("permalink")
    except Exception as exc:
        logger.warning("publication_permalink_failed", pub_id=pub["id"], error=str(exc))

    await store.mark_published(
        pool, pub["id"], ig_media_id=media_id, permalink=permalink
    )
    logger.info(
        "publication_published", pub_id=pub["id"], kind=pub["kind"], media_id=media_id
    )


async def publish_next(pool: AsyncConnectionPool, instagram: InstagramClient) -> bool:
    """Avança uma publicação devida, se houver.

    Returns:
        True se alguma publicação foi trabalhada.
    """
    pub = await store.claim_due(pool, LEASE_SECONDS)
    if pub is None:
        return False

    try:
        ig_user_id = await _account_id(instagram)
        if pub["status"] == "scheduled":
            await _create_containers(pool, instagram, pub, ig_user_id)
        else:
            await _publish(pool, instagram, pub, ig_user_id)
    except Exception as exc:
        if pub["status"] == "publishing" or (
            pub["status"] == "processing" and pub["container_id"]
        ):
            # O media_publish pode ter dado certo do lado da Meta: NÃO recria
            # o container; confere o status na próxima passada.
            if is_transient(exc) and pub["attempts"] + 1 < MAX_TRANSIENT_ATTEMPTS:
                await store.check_again_in(pool, pub["id"], 30, count_attempt=True)
                logger.warning(
                    "publication_retry_check", pub_id=pub["id"], error=str(exc)
                )
                return True
            await store.mark_failed(
                pool,
                pub["id"],
                f"{describe_error(exc)} Confira no Instagram se a publicação já "
                "está no ar antes de reagendar, para não publicar em dobro.",
            )
            return True
        await _fail_or_postpone(pool, pub, exc)
    return True
