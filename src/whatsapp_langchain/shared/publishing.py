"""Publicações no Instagram (Feed, Story, Reels): regras e acesso ao banco.

Tabelas `ig_publications` e `ig_publication_media` (migration 010).

- `validate_publication`: regras da Meta conferidas ANTES de aprovar, para o
  erro aparecer no painel e não horas depois, no horário agendado.
- Painel (`server/routes/publishing.py`): cria, edita, aprova, cancela.
- Worker (`worker/publisher.py`): publica quando chega a hora.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from psycopg_pool import AsyncConnectionPool

# ---------------------------------------------------------------------------
# Regras da Meta
# ---------------------------------------------------------------------------

MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 30
MAX_MENTIONS = 20
MAX_CAROUSEL_ITEMS = 10

# Proporção (largura/altura) aceita no feed: de 4:5 (retrato) a 1.91:1.
FEED_MIN_RATIO = 4 / 5
FEED_MAX_RATIO = 1.91
# Story e Reels: tela cheia 9:16.
VERTICAL_RATIO = 9 / 16

REELS_MIN_SECONDS = 3
REELS_MAX_SECONDS = 15 * 60
STORY_MAX_VIDEO_SECONDS = 60
STORY_MAX_VIDEO_BYTES = 100 * 1024 * 1024

_HASHTAG = re.compile(r"(?<!\w)#\w+", re.UNICODE)
_MENTION = re.compile(r"(?<![\w@])@[\w.]+", re.UNICODE)

KINDS = ("feed", "story", "reels")
EDITABLE_STATUSES = ("draft", "failed")

_RESET_CHILD_CONTAINERS = (
    "UPDATE ig_publication_media SET container_id = NULL WHERE publication_id = %s"
)


@dataclass
class MediaInfo:
    media_kind: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    size_bytes: int = 0


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def count_hashtags(text: str) -> int:
    return len(_HASHTAG.findall(text))


def count_mentions(text: str) -> int:
    return len(_MENTION.findall(text))


def _ratio(m: MediaInfo) -> float | None:
    if m.width and m.height:
        return m.width / m.height
    return None


def validate_publication(kind: str, caption: str, media: list[MediaInfo]) -> Validation:
    """Confere as regras da Meta para o tipo de publicação.

    Erros bloqueiam a aprovação; avisos só aparecem no painel.
    """
    v = Validation()
    if kind not in KINDS:
        v.errors.append(f"Tipo inválido: {kind}")
        return v

    images = [m for m in media if m.media_kind == "image"]
    videos = [m for m in media if m.media_kind == "video"]

    # --- Quantidade e tipo de mídia ---
    if not media:
        v.errors.append("Adicione a mídia da publicação.")
    elif kind == "story" and len(media) != 1:
        v.errors.append("Story leva exatamente 1 foto ou vídeo.")
    elif kind == "reels" and (len(media) != 1 or not videos):
        v.errors.append("Reels leva exatamente 1 vídeo.")
    elif kind == "feed":
        if len(media) > MAX_CAROUSEL_ITEMS:
            v.errors.append(f"Carrossel aceita no máximo {MAX_CAROUSEL_ITEMS} itens.")
        if len(media) == 1 and videos:
            v.errors.append(
                "Vídeo sozinho no feed é publicado como Reels: troque o tipo "
                "para Reels (com 'Mostrar também no feed' ligado)."
            )

    # --- Proporção ---
    if kind == "feed":
        for i, m in enumerate(images, start=1):
            r = _ratio(m)
            if r and not (FEED_MIN_RATIO - 0.01 <= r <= FEED_MAX_RATIO + 0.01):
                v.errors.append(
                    f"Foto {i} fora da proporção do feed ({m.width}x{m.height}). "
                    "Use entre 4:5 (retrato) e 1,91:1 (paisagem)."
                )
        ratios = {round(r, 2) for m in media if (r := _ratio(m))}
        if len(media) > 1 and len(ratios) > 1:
            v.warnings.append(
                "Fotos do carrossel com proporções diferentes: o Instagram corta "
                "todas na proporção da primeira."
            )
    elif media:
        r = _ratio(media[0])
        if r and abs(r - VERTICAL_RATIO) > 0.05:
            v.warnings.append(
                "Story e Reels ficam melhores em 9:16 (vertical, ex: 1080x1920). "
                "Outras proporções aparecem com bordas ou cortadas."
            )

    # --- Vídeo ---
    for m in videos:
        d = m.duration_seconds
        if kind == "reels" and d is not None:
            if d < REELS_MIN_SECONDS:
                v.errors.append(
                    f"Reels precisa ter pelo menos {REELS_MIN_SECONDS} segundos."
                )
            elif d > REELS_MAX_SECONDS:
                v.errors.append("Reels pode ter no máximo 15 minutos.")
        if kind == "story":
            if d is not None and d > STORY_MAX_VIDEO_SECONDS:
                v.errors.append("Vídeo de Story pode ter no máximo 60 segundos.")
            if m.size_bytes > STORY_MAX_VIDEO_BYTES:
                v.errors.append("Vídeo de Story pode ter no máximo 100 MB.")
        if d is None:
            v.warnings.append(
                "Não deu para ler a duração do vídeo: a Meta confere ao processar."
            )

    # --- Legenda ---
    if kind == "story":
        if caption.strip():
            v.warnings.append("Story não tem legenda: o texto não será publicado.")
    else:
        if len(caption) > MAX_CAPTION_CHARS:
            v.errors.append(f"Legenda passa de {MAX_CAPTION_CHARS} caracteres.")
        if count_hashtags(caption) > MAX_HASHTAGS:
            v.errors.append(f"Máximo de {MAX_HASHTAGS} hashtags.")
        if count_mentions(caption) > MAX_MENTIONS:
            v.errors.append(f"Máximo de {MAX_MENTIONS} menções (@).")
        if not caption.strip():
            v.warnings.append("Publicação sem legenda.")

    return v


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------

_PUB_COLUMNS = (
    "id, kind, status, brief, caption, ai_caption, share_to_feed, publish_at, "
    "container_id, ig_media_id, permalink, error, attempts, created_by, "
    "approved_by, published_at, created_at, updated_at, container_created_at, "
    "origin, planned_for, rationale"
)
_MEDIA_COLUMNS = (
    "id, publication_id, position, token, media_kind, content_type, size_bytes, "
    "width, height, duration_seconds, original_name, ai_description, container_id"
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _pub_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "kind": row[1],
        "status": row[2],
        "brief": row[3],
        "caption": row[4],
        "ai_caption": row[5],
        "share_to_feed": row[6],
        "publish_at": _iso(row[7]),
        "container_id": row[8],
        "ig_media_id": row[9],
        "permalink": row[10],
        "error": row[11],
        "attempts": row[12],
        "created_by": row[13],
        "approved_by": row[14],
        "published_at": _iso(row[15]),
        "created_at": _iso(row[16]),
        "updated_at": _iso(row[17]),
        "container_created_at": _iso(row[18]),
        "origin": row[19],
        "planned_for": _iso(row[20]),
        "rationale": row[21],
    }


def _media_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "publication_id": row[1],
        "position": row[2],
        "token": row[3],
        "media_kind": row[4],
        "content_type": row[5],
        "size_bytes": row[6],
        "width": row[7],
        "height": row[8],
        "duration_seconds": row[9],
        "original_name": row[10],
        "ai_description": row[11],
        "container_id": row[12],
    }


def media_info(media: list[dict]) -> list[MediaInfo]:
    return [
        MediaInfo(
            media_kind=m["media_kind"],
            width=m["width"],
            height=m["height"],
            duration_seconds=m["duration_seconds"],
            size_bytes=m["size_bytes"],
        )
        for m in media
    ]


async def create_publication(
    pool: AsyncConnectionPool, *, kind: str, created_by: str
) -> int:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO ig_publications (kind, created_by) VALUES (%s, %s)
            RETURNING id
            """,
            (kind, created_by),
        )
        row = await cursor.fetchone()
        await conn.commit()
    return row[0]


async def create_suggested_draft(
    pool: AsyncConnectionPool,
    *,
    kind: str,
    brief: str,
    caption: str,
    planned_for: datetime | None,
    rationale: str,
    created_by: str,
) -> int:
    """Rascunho sugerido pelo agente de marketing (sem mídia, sem aprovação).

    A equipe sobe a mídia e aprova na tela Publicar. A legenda entra também
    em `ai_caption`, para dar para comparar com a versão final editada.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO ig_publications
                (kind, brief, caption, ai_caption, planned_for, rationale,
                 origin, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'agent', %s)
            RETURNING id
            """,
            (kind, brief, caption, caption or None, planned_for, rationale, created_by),
        )
        row = await cursor.fetchone()
        await conn.commit()
    return row[0]


async def content_calendar(
    pool: AsyncConnectionPool, *, since: datetime, until: datetime
) -> list[dict]:
    """Publicações (exceto descartadas) com data no intervalo, para o agente.

    A data considerada é a de publicação, a agendada ou a sugerida, nessa ordem.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, kind, status, origin, brief, caption,
                   COALESCE(published_at, publish_at, planned_for) AS day,
                   (SELECT COUNT(*) FROM ig_publication_media m
                     WHERE m.publication_id = p.id) AS media_count
            FROM ig_publications p
            WHERE status <> 'canceled'
              AND COALESCE(published_at, publish_at, planned_for, created_at)
                  BETWEEN %s AND %s
            ORDER BY day NULLS LAST, id
            """,
            (since, until),
        )
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "kind": r[1],
            "status": r[2],
            "origin": r[3],
            "brief": r[4],
            "caption": r[5],
            "date": _iso(r[6]),
            "media_count": r[7],
        }
        for r in rows
    ]


async def get_publication(pool: AsyncConnectionPool, pub_id: int) -> dict | None:
    """Publicação com a lista de mídia (na ordem do carrossel)."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"SELECT {_PUB_COLUMNS} FROM ig_publications WHERE id = %s", (pub_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cursor = await conn.execute(
            f"""
            SELECT {_MEDIA_COLUMNS} FROM ig_publication_media
            WHERE publication_id = %s ORDER BY position, id
            """,
            (pub_id,),
        )
        media = [_media_row(r) for r in await cursor.fetchall()]
    pub = _pub_row(row)
    pub["media"] = media
    return pub


async def list_publications(pool: AsyncConnectionPool, limit: int = 100) -> list[dict]:
    """Publicações (com a primeira mídia como capa), mais recentes antes."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            SELECT {", ".join("p." + c.strip() for c in _PUB_COLUMNS.split(","))},
                   cover.token, cover.media_kind,
                   (SELECT COUNT(*) FROM ig_publication_media m
                     WHERE m.publication_id = p.id) AS media_count
            FROM ig_publications p
            LEFT JOIN LATERAL (
                SELECT token, media_kind FROM ig_publication_media m
                WHERE m.publication_id = p.id ORDER BY position, id LIMIT 1
            ) cover ON TRUE
            WHERE p.status <> 'canceled'
            ORDER BY COALESCE(p.published_at, p.publish_at, p.created_at) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    n = len(_PUB_COLUMNS.split(","))
    result = []
    for row in rows:
        pub = _pub_row(row[:n])
        pub["cover_token"] = row[n]
        pub["cover_kind"] = row[n + 1]
        pub["media_count"] = row[n + 2]
        result.append(pub)
    return result


async def update_draft(
    pool: AsyncConnectionPool,
    pub_id: int,
    *,
    kind: str | None = None,
    brief: str | None = None,
    caption: str | None = None,
    share_to_feed: bool | None = None,
    ai_caption: str | None = None,
) -> bool:
    """Edita uma publicação que ainda não foi aprovada (draft/failed)."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE ig_publications SET
                kind = COALESCE(%s, kind),
                brief = COALESCE(%s, brief),
                caption = COALESCE(%s, caption),
                share_to_feed = COALESCE(%s, share_to_feed),
                ai_caption = COALESCE(%s, ai_caption),
                updated_at = NOW()
            WHERE id = %s AND status = ANY(%s)
            RETURNING id
            """,
            (
                kind,
                brief,
                caption,
                share_to_feed,
                ai_caption,
                pub_id,
                list(EDITABLE_STATUSES),
            ),
        )
        changed = await cursor.fetchone() is not None
        await conn.commit()
    return changed


async def add_media(
    pool: AsyncConnectionPool,
    pub_id: int,
    *,
    token: str,
    media_kind: str,
    content_type: str,
    size_bytes: int,
    width: int | None,
    height: int | None,
    duration_seconds: float | None,
    original_name: str | None,
) -> dict:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            INSERT INTO ig_publication_media
                (publication_id, position, token, media_kind, content_type,
                 size_bytes, width, height, duration_seconds, original_name)
            VALUES (
                %s,
                (SELECT COALESCE(MAX(position) + 1, 0) FROM ig_publication_media
                  WHERE publication_id = %s),
                %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_MEDIA_COLUMNS}
            """,
            (
                pub_id,
                pub_id,
                token,
                media_kind,
                content_type,
                size_bytes,
                width,
                height,
                duration_seconds,
                original_name,
            ),
        )
        row = await cursor.fetchone()
        await conn.commit()
    return _media_row(row)


async def delete_media(
    pool: AsyncConnectionPool, pub_id: int, media_id: int
) -> str | None:
    """Remove uma mídia; devolve o token (para apagar o arquivo)."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            DELETE FROM ig_publication_media
            WHERE id = %s AND publication_id = %s
            RETURNING token
            """,
            (media_id, pub_id),
        )
        row = await cursor.fetchone()
        await conn.commit()
    return row[0] if row else None


async def reorder_media(
    pool: AsyncConnectionPool, pub_id: int, media_ids: list[int]
) -> None:
    async with pool.connection() as conn:
        for position, media_id in enumerate(media_ids):
            await conn.execute(
                """
                UPDATE ig_publication_media SET position = %s
                WHERE id = %s AND publication_id = %s
                """,
                (position, media_id, pub_id),
            )
        await conn.commit()


async def set_media_description(
    pool: AsyncConnectionPool, media_id: int, description: str
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE ig_publication_media SET ai_description = %s WHERE id = %s",
            (description, media_id),
        )
        await conn.commit()


async def schedule(
    pool: AsyncConnectionPool, pub_id: int, *, publish_at: datetime, approved_by: str
) -> bool:
    """Aprova: o Worker publica quando `publish_at` chegar."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE ig_publications SET
                status = 'scheduled', publish_at = %s, approved_by = %s,
                error = NULL, attempts = 0, lease_until = NULL,
                container_id = NULL, container_created_at = NULL,
                updated_at = NOW()
            WHERE id = %s AND status = ANY(%s)
            RETURNING id
            """,
            (publish_at, approved_by, pub_id, list(EDITABLE_STATUSES)),
        )
        changed = await cursor.fetchone() is not None
        if changed:
            await conn.execute(
                _RESET_CHILD_CONTAINERS,
                (pub_id,),
            )
        await conn.commit()
    return changed


async def unschedule(pool: AsyncConnectionPool, pub_id: int) -> bool:
    """Volta um agendado (que ainda não começou a subir) para rascunho."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE ig_publications SET status = 'draft', updated_at = NOW()
            WHERE id = %s AND status = 'scheduled'
              AND (lease_until IS NULL OR lease_until < NOW())
            RETURNING id
            """,
            (pub_id,),
        )
        changed = await cursor.fetchone() is not None
        await conn.commit()
    return changed


async def cancel(pool: AsyncConnectionPool, pub_id: int) -> list[str] | None:
    """Descarta um rascunho/falha/agendado. Devolve os tokens para apagar."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE ig_publications SET status = 'canceled', updated_at = NOW()
            WHERE id = %s AND status IN ('draft', 'failed', 'scheduled')
              AND (lease_until IS NULL OR lease_until < NOW())
            RETURNING id
            """,
            (pub_id,),
        )
        if await cursor.fetchone() is None:
            await conn.commit()
            return None
        cursor = await conn.execute(
            "SELECT token FROM ig_publication_media WHERE publication_id = %s",
            (pub_id,),
        )
        tokens = [r[0] for r in await cursor.fetchall()]
        await conn.commit()
    return tokens


# --- Worker -----------------------------------------------------------------


async def claim_due(pool: AsyncConnectionPool, lease_seconds: int) -> dict | None:
    """Reserva a próxima publicação com trabalho a fazer.

    - `scheduled` com `publish_at` vencido: criar o container.
    - `processing` com `lease_until` vencido: conferir se a Meta terminou de
      processar (aqui `lease_until` é "próxima checagem").
    - `publishing` com lease vencido: o processo caiu no meio do
      media_publish; o Worker confere o container antes de tentar de novo.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            UPDATE ig_publications SET
                lease_until = NOW() + make_interval(secs => %s),
                updated_at = NOW()
            WHERE id = (
                SELECT id FROM ig_publications
                WHERE (status = 'scheduled' AND publish_at <= NOW()
                       AND (lease_until IS NULL OR lease_until < NOW()))
                   OR (status IN ('processing', 'publishing') AND lease_until < NOW())
                ORDER BY publish_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING {_PUB_COLUMNS}
            """,
            (lease_seconds,),
        )
        row = await cursor.fetchone()
        await conn.commit()
    if row is None:
        return None
    return await get_publication(pool, row[0])


async def set_child_container(
    pool: AsyncConnectionPool, media_id: int, container_id: str
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE ig_publication_media SET container_id = %s WHERE id = %s",
            (container_id, media_id),
        )
        await conn.commit()


async def set_processing(
    pool: AsyncConnectionPool, pub_id: int, container_id: str, check_in_seconds: int
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_publications SET
                status = 'processing', container_id = %s,
                container_created_at = NOW(),
                lease_until = NOW() + make_interval(secs => %s),
                updated_at = NOW()
            WHERE id = %s
            """,
            (container_id, check_in_seconds, pub_id),
        )
        await conn.commit()


async def check_again_in(
    pool: AsyncConnectionPool, pub_id: int, seconds: int, *, count_attempt: bool = False
) -> None:
    """Agenda a próxima checagem (`count_attempt`: conta como tentativa falha)."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_publications SET
                lease_until = NOW() + make_interval(secs => %s),
                attempts = attempts + %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (seconds, int(count_attempt), pub_id),
        )
        await conn.commit()


async def set_publishing(
    pool: AsyncConnectionPool, pub_id: int, lease_seconds: int
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_publications SET status = 'publishing',
                lease_until = NOW() + make_interval(secs => %s), updated_at = NOW()
            WHERE id = %s
            """,
            (lease_seconds, pub_id),
        )
        await conn.commit()


async def mark_published(
    pool: AsyncConnectionPool,
    pub_id: int,
    *,
    ig_media_id: str | None,
    permalink: str | None,
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_publications SET
                status = 'published', ig_media_id = %s, permalink = %s,
                published_at = NOW(), error = NULL, lease_until = NULL,
                updated_at = NOW()
            WHERE id = %s
            """,
            (ig_media_id, permalink, pub_id),
        )
        await conn.commit()


async def mark_failed(pool: AsyncConnectionPool, pub_id: int, error: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_publications SET
                status = 'failed', error = %s, lease_until = NULL,
                attempts = attempts + 1, updated_at = NOW()
            WHERE id = %s
            """,
            (error[:1000], pub_id),
        )
        await conn.commit()


async def postpone(
    pool: AsyncConnectionPool, pub_id: int, seconds: int, reason: str
) -> None:
    """Adia uma publicação agendada (cota diária da Meta ou falha transitória)."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_publications SET
                status = 'scheduled', error = %s, attempts = attempts + 1,
                container_id = NULL, container_created_at = NULL,
                lease_until = NOW() + make_interval(secs => %s), updated_at = NOW()
            WHERE id = %s
            """,
            (reason[:1000], seconds, pub_id),
        )
        await conn.execute(
            _RESET_CHILD_CONTAINERS,
            (pub_id,),
        )
        await conn.commit()
