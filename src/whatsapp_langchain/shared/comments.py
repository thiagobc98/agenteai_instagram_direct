"""Postagens e comentários do Instagram (tabelas `ig_posts` e `ig_comments`).

Migration 009. Quem escreve aqui:
- Webhook (`server/routes/webhook_instagram.py`): grava comentários novos.
- Worker (`worker/comments.py`): gera o rascunho de resposta da IA.
- Painel (`server/routes/comments.py`): sincroniza postagens, aprova, edita,
  ignora e publica as respostas.

Ciclo de status do comentário: ver o cabeçalho da migration 009.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

# Statuses em que o painel ainda pode agir sobre o comentário.
ACTIONABLE_STATUSES = ("new", "drafting", "pending", "failed")

# Tentativas de gerar rascunho antes de desistir (status `failed`).
MAX_DRAFT_ATTEMPTS = 3

# Backoff entre tentativas de rascunho: 30s, 2min, 8min...
DRAFT_RETRY_BASE_SECONDS = 30

# Publicação interrompida (API caiu no meio): depois disso o comentário em
# `sending` pode ser aprovado de novo. O que já foi publicado
# (`reply_public_id` / `reply_private_id`) não é reenviado.
SENDING_STALE_SECONDS = 120


def draft_retry_delay_seconds(attempts: int) -> int:
    """Espera antes da próxima tentativa de rascunho (exponencial, base 4)."""
    return DRAFT_RETRY_BASE_SECONDS * 4 ** max(attempts - 1, 0)


@dataclass
class CommentForDraft:
    """Comentário reservado pelo Worker para gerar o rascunho."""

    comment_id: str
    media_id: str
    text: str
    from_username: str | None
    parent_id: str | None
    attempts: int
    post_caption: str | None
    post_synced: bool


_POST_COLUMNS = (
    "media_id, caption, media_type, media_url, thumbnail_url, permalink, "
    "posted_at, comments_count, synced_at"
)

_COMMENT_COLUMNS = (
    "comment_id, media_id, parent_id, from_id, from_username, text, "
    "commented_at, status, draft_public, draft_private, ai_suggests_ignore, "
    "ai_reason, reply_public_id, reply_public_text, reply_private_id, "
    "reply_private_text, private_error, error, sent_at, approved_by"
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _post_row(row: tuple) -> dict:
    return {
        "media_id": row[0],
        "caption": row[1],
        "media_type": row[2],
        "media_url": row[3],
        "thumbnail_url": row[4],
        "permalink": row[5],
        "posted_at": _iso(row[6]),
        "comments_count": row[7],
        "synced_at": _iso(row[8]),
    }


def _comment_row(row: tuple) -> dict:
    return {
        "comment_id": row[0],
        "media_id": row[1],
        "parent_id": row[2],
        "from_id": row[3],
        "from_username": row[4],
        "text": row[5],
        "commented_at": _iso(row[6]),
        "status": row[7],
        "draft_public": row[8],
        "draft_private": row[9],
        "ai_suggests_ignore": row[10],
        "ai_reason": row[11],
        "reply_public_id": row[12],
        "reply_public_text": row[13],
        "reply_private_id": row[14],
        "reply_private_text": row[15],
        "private_error": row[16],
        "error": row[17],
        "sent_at": _iso(row[18]),
        "approved_by": row[19],
    }


# ---------------------------------------------------------------------------
# Escrita: postagens
# ---------------------------------------------------------------------------


async def upsert_post(pool: AsyncConnectionPool, post: dict) -> None:
    """Cria ou atualiza uma postagem com os dados da Graph API (`/me/media`)."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO ig_posts (media_id, caption, media_type, media_url,
                                  thumbnail_url, permalink, posted_at,
                                  comments_count, synced_at)
            VALUES (%(id)s, %(caption)s, %(media_type)s, %(media_url)s,
                    %(thumbnail_url)s, %(permalink)s, %(timestamp)s,
                    %(comments_count)s, NOW())
            ON CONFLICT (media_id) DO UPDATE SET
                caption = EXCLUDED.caption,
                media_type = EXCLUDED.media_type,
                media_url = EXCLUDED.media_url,
                thumbnail_url = EXCLUDED.thumbnail_url,
                permalink = EXCLUDED.permalink,
                posted_at = EXCLUDED.posted_at,
                comments_count = EXCLUDED.comments_count,
                synced_at = NOW()
            """,
            {
                "id": post["id"],
                "caption": post.get("caption"),
                "media_type": post.get("media_type"),
                "media_url": post.get("media_url"),
                "thumbnail_url": post.get("thumbnail_url"),
                "permalink": post.get("permalink"),
                "timestamp": post.get("timestamp"),
                "comments_count": post.get("comments_count"),
            },
        )
        await conn.commit()


async def ensure_post_stub(pool: AsyncConnectionPool, media_id: str) -> None:
    """Garante uma linha da postagem (sem detalhes) para um comentário recebido.

    Os detalhes (legenda, imagem) são buscados depois pelo Worker ou na
    sincronização do painel.
    """
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO ig_posts (media_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (media_id,),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Escrita: comentários
# ---------------------------------------------------------------------------


async def insert_comment(
    pool: AsyncConnectionPool,
    *,
    comment_id: str,
    media_id: str,
    text: str,
    from_id: str | None,
    from_username: str | None,
    parent_id: str | None,
    commented_at: datetime,
    status: str = "new",
) -> bool:
    """Grava um comentário recebido. Idempotente (a Meta reenvia eventos).

    Comentários cujo ID é uma resposta já publicada pelo painel viram
    `ignored` (é a própria conta respondendo, não precisa de rascunho).

    Returns:
        True se o comentário é novo.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM ig_comments WHERE reply_public_id = %s",
            (comment_id,),
        )
        if await cursor.fetchone():
            status = "ignored"

        await conn.execute(
            "INSERT INTO ig_posts (media_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (media_id,),
        )
        cursor = await conn.execute(
            """
            INSERT INTO ig_comments (comment_id, media_id, parent_id, from_id,
                                     from_username, text, commented_at, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (comment_id) DO NOTHING
            RETURNING comment_id
            """,
            (
                comment_id,
                media_id,
                parent_id,
                from_id,
                from_username,
                text,
                commented_at,
                status,
            ),
        )
        created = await cursor.fetchone() is not None
        await conn.commit()
        return created


async def claim_next_comment_for_draft(
    pool: AsyncConnectionPool, lease_seconds: int = 60
) -> CommentForDraft | None:
    """Reserva o próximo comentário `new` (ou `drafting` com lease vencido).

    Em `new`, `lease_until` funciona como "não tentar antes de" (backoff
    gravado por `mark_draft_failed`). Usa FOR UPDATE SKIP LOCKED, como a fila
    de mensagens, para permitir mais de um Worker.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE ig_comments SET
                status = 'drafting',
                attempts = attempts + 1,
                lease_until = NOW() + make_interval(secs => %s),
                updated_at = NOW()
            WHERE comment_id = (
                SELECT comment_id FROM ig_comments
                WHERE (status = 'new' AND (lease_until IS NULL OR lease_until <= NOW()))
                   OR (status = 'drafting' AND lease_until < NOW())
                ORDER BY commented_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING comment_id, media_id, text, from_username, parent_id, attempts
            """,
            (lease_seconds,),
        )
        row = await cursor.fetchone()
        if row is None:
            await conn.commit()
            return None

        cursor = await conn.execute(
            "SELECT caption, synced_at IS NOT NULL FROM ig_posts WHERE media_id = %s",
            (row[1],),
        )
        post = await cursor.fetchone()
        await conn.commit()

    return CommentForDraft(
        comment_id=row[0],
        media_id=row[1],
        text=row[2],
        from_username=row[3],
        parent_id=row[4],
        attempts=row[5],
        post_caption=post[0] if post else None,
        post_synced=bool(post[1]) if post else False,
    )


async def save_draft(
    pool: AsyncConnectionPool,
    comment_id: str,
    *,
    draft_public: str,
    draft_private: str,
    suggests_ignore: bool,
    reason: str | None,
) -> None:
    """Grava o rascunho da IA e deixa o comentário aguardando aprovação."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_comments SET
                status = 'pending',
                draft_public = %s,
                draft_private = %s,
                ai_suggests_ignore = %s,
                ai_reason = %s,
                error = NULL,
                lease_until = NULL,
                updated_at = NOW()
            WHERE comment_id = %s AND status = 'drafting'
            """,
            (draft_public, draft_private, suggests_ignore, reason, comment_id),
        )
        await conn.commit()


async def mark_draft_failed(
    pool: AsyncConnectionPool, comment_id: str, error: str, attempts: int
) -> None:
    """Falha ao gerar rascunho: volta para `new` com backoff, ou desiste (`failed`).

    Sem o backoff, uma queda curta do provedor de LLM queimaria as tentativas
    de todos os comentários em segundos.
    """
    give_up = attempts >= MAX_DRAFT_ATTEMPTS
    status = "failed" if give_up else "new"
    delay = None if give_up else draft_retry_delay_seconds(attempts)
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_comments SET
                status = %s,
                error = %s,
                lease_until = CASE WHEN %s::int IS NULL THEN NULL
                                   ELSE NOW() + make_interval(secs => %s::int) END,
                updated_at = NOW()
            WHERE comment_id = %s
            """,
            (status, error[:500], delay, delay, comment_id),
        )
        await conn.commit()


async def request_redraft(pool: AsyncConnectionPool, comment_id: str) -> bool:
    """Pede um rascunho novo à IA (painel). Zera as tentativas."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE ig_comments SET status = 'new', attempts = 0, error = NULL,
                                   lease_until = NULL, updated_at = NOW()
            WHERE comment_id = %s AND status IN ('pending', 'failed', 'ignored')
              AND reply_public_id IS NULL
            RETURNING comment_id
            """,
            (comment_id,),
        )
        changed = await cursor.fetchone() is not None
        await conn.commit()
        return changed


async def set_status(pool: AsyncConnectionPool, comment_id: str, status: str) -> bool:
    """Muda o status (ignorar / reabrir) de um comentário ainda não respondido."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE ig_comments SET status = %s, updated_at = NOW()
            WHERE comment_id = %s AND status NOT IN ('sent', 'sending')
            RETURNING comment_id
            """,
            (status, comment_id),
        )
        changed = await cursor.fetchone() is not None
        await conn.commit()
        return changed


async def claim_for_sending(
    pool: AsyncConnectionPool, comment_id: str, approved_by: str
) -> dict | None:
    """Reserva o comentário para publicação (status `sending`).

    Atômico: dois cliques em "Aprovar" não publicam a resposta duas vezes.
    Um `sending` parado há mais de SENDING_STALE_SECONDS (processo caiu no
    meio) pode ser reservado de novo.

    Returns:
        O comentário reservado, ou None se ele não está apto a ser respondido.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            UPDATE ig_comments SET status = 'sending', approved_by = %s,
                                   updated_at = NOW()
            WHERE comment_id = %s
              AND (status IN ('new', 'pending', 'failed')
                   OR (status = 'sending'
                       AND updated_at < NOW() - make_interval(secs => %s)))
            RETURNING {_COMMENT_COLUMNS}
            """,
            (approved_by, comment_id, SENDING_STALE_SECONDS),
        )
        row = await cursor.fetchone()
        await conn.commit()
    return _comment_row(row) if row else None


async def record_public_reply(
    pool: AsyncConnectionPool, comment_id: str, reply_id: str, text: str
) -> None:
    """Registra a resposta pública publicada (antes de tentar a privada)."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_comments SET reply_public_id = %s, reply_public_text = %s,
                                   updated_at = NOW()
            WHERE comment_id = %s
            """,
            (reply_id, text, comment_id),
        )
        await conn.commit()


async def finish_reply(
    pool: AsyncConnectionPool,
    comment_id: str,
    *,
    private_id: str | None,
    private_text: str | None,
    private_error: str | None,
) -> None:
    """Fecha o comentário como respondido (`sent`)."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_comments SET
                status = 'sent',
                reply_private_id = COALESCE(%s, reply_private_id),
                reply_private_text = COALESCE(%s, reply_private_text),
                private_error = %s,
                error = NULL,
                sent_at = NOW(),
                updated_at = NOW()
            WHERE comment_id = %s
            """,
            (private_id, private_text, private_error, comment_id),
        )
        await conn.commit()


async def mark_reply_failed(
    pool: AsyncConnectionPool, comment_id: str, error: str
) -> None:
    """Falha ao publicar a resposta pública: mantém o rascunho para nova tentativa."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE ig_comments SET status = 'failed', error = %s, updated_at = NOW()
            WHERE comment_id = %s
            """,
            (error[:500], comment_id),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Leitura (painel)
# ---------------------------------------------------------------------------


async def list_posts(pool: AsyncConnectionPool, limit: int = 60) -> list[dict]:
    """Postagens com contagem de comentários por status, mais recentes antes."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT p.media_id, p.caption, p.media_type, p.media_url,
                   p.thumbnail_url, p.permalink, p.posted_at, p.comments_count,
                   p.synced_at,
                   COUNT(c.comment_id) AS total,
                   COUNT(c.comment_id) FILTER (
                       WHERE c.status IN ('new', 'drafting', 'pending', 'failed')
                   ) AS pending,
                   MAX(c.commented_at) AS last_comment_at
            FROM ig_posts p
            LEFT JOIN ig_comments c ON c.media_id = p.media_id
            GROUP BY p.media_id
            ORDER BY COALESCE(p.posted_at, p.created_at) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

    posts = []
    for row in rows:
        post = _post_row(row[:9])
        post["tracked_comments"] = row[9]
        post["pending_comments"] = row[10]
        post["last_comment_at"] = _iso(row[11])
        posts.append(post)
    return posts


async def get_post(pool: AsyncConnectionPool, media_id: str) -> dict | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"SELECT {_POST_COLUMNS} FROM ig_posts WHERE media_id = %s",
            (media_id,),
        )
        row = await cursor.fetchone()
    return _post_row(row) if row else None


async def list_comments(
    pool: AsyncConnectionPool,
    *,
    media_id: str | None = None,
    statuses: tuple[str, ...] | None = None,
    limit: int = 200,
    newest_first: bool = False,
) -> list[dict]:
    """Comentários filtrados por postagem e/ou status.

    Padrão: ordem cronológica (como no Instagram; na fila, responde na ordem).
    `newest_first` inverte, e o LIMIT passa a manter os mais recentes.
    """
    where: list[str] = []
    params: list = []
    if media_id:
        where.append("media_id = %s")
        params.append(media_id)
    if statuses:
        where.append("status = ANY(%s)")
        params.append(list(statuses))
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)

    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            SELECT {_COMMENT_COLUMNS} FROM ig_comments {clause}
            ORDER BY commented_at {"DESC" if newest_first else "ASC"}, comment_id
            LIMIT %s
            """,
            params,
        )
        rows = await cursor.fetchall()
    return [_comment_row(row) for row in rows]


async def get_comment(pool: AsyncConnectionPool, comment_id: str) -> dict | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"SELECT {_COMMENT_COLUMNS} FROM ig_comments WHERE comment_id = %s",
            (comment_id,),
        )
        row = await cursor.fetchone()
    return _comment_row(row) if row else None


async def comment_counts(pool: AsyncConnectionPool) -> dict[str, int]:
    """Total de comentários por status (para o resumo do painel)."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT status, COUNT(*) FROM ig_comments GROUP BY status"
        )
        rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


# Até quando a resposta no Direct a uma mensagem privada de comentário ainda
# é tratada como continuação daquela conversa.
COMMENT_CONTEXT_DAYS = 7


@dataclass(frozen=True)
class CommentContext:
    """Comentário que levou a cliente ao Direct, e o que já mandamos a ela."""

    comment_text: str
    private_text: str
    post_caption: str | None
    sent_at: datetime


async def recent_private_reply(
    pool: AsyncConnectionPool, from_id: str, days: int = COMMENT_CONTEXT_DAYS
) -> CommentContext | None:
    """Última mensagem privada enviada no Direct a quem comentou num post.

    A mensagem privada é enviada pela tela de comentários, fora da conversa do
    agente do Direct. Quando a cliente responde no Direct, o agente usa isto
    para continuar o assunto (sem se apresentar de novo nem pedir o WhatsApp
    outra vez). O `from_id` do comentário é o mesmo ID que chega nas mensagens
    do Direct (Instagram Login).
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT c.text, c.reply_private_text, p.caption, c.sent_at
            FROM ig_comments c
            LEFT JOIN ig_posts p ON p.media_id = c.media_id
            WHERE c.from_id = %s
              AND c.reply_private_id IS NOT NULL
              AND c.reply_private_text <> ''
              AND c.sent_at > NOW() - make_interval(days => %s)
            ORDER BY c.sent_at DESC
            LIMIT 1
            """,
            (from_id, days),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return CommentContext(
        comment_text=row[0] or "",
        private_text=row[1],
        post_caption=row[2],
        sent_at=row[3],
    )


async def list_private_replies(
    pool: AsyncConnectionPool, from_id: str, limit: int = 50
) -> list[dict]:
    """Mensagens privadas enviadas no Direct a partir de comentários desta
    pessoa, para aparecerem na conversa do painel junto com o Direct."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT c.comment_id, c.text, c.commented_at, c.reply_private_text,
                   c.sent_at, c.approved_by, p.permalink, p.caption
            FROM ig_comments c
            LEFT JOIN ig_posts p ON p.media_id = c.media_id
            WHERE c.from_id = %s AND c.reply_private_id IS NOT NULL
            ORDER BY c.sent_at DESC
            LIMIT %s
            """,
            (from_id, limit),
        )
        rows = await cursor.fetchall()
    return [
        {
            "comment_id": r[0],
            "comment_text": r[1],
            "commented_at": _iso(r[2]),
            "private_text": r[3],
            "sent_at": _iso(r[4]),
            "approved_by": r[5],
            "post_permalink": r[6],
            "post_caption": (r[7] or "")[:120] or None,
        }
        for r in rows
    ]


async def register_dm_from_comment(
    pool: AsyncConnectionPool,
    *,
    from_id: str,
    username: str | None,
    agent_id: str,
    private_text: str,
) -> None:
    """Coloca na lista de conversas do painel quem recebeu a mensagem privada
    de um comentário, mesmo antes de responder no Direct.

    O @ só é gravado se o contato ainda não tiver um (o perfil completo vem
    depois, pela rotina de perfis). Não conta como mensagem trocada: não mexe
    em `message_count` de quem já conversava.
    """
    thread_id = f"{from_id}:{agent_id}"
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO contacts (external_id, username)
            VALUES (%s, %s)
            ON CONFLICT (external_id) DO UPDATE SET
                username = COALESCE(contacts.username, EXCLUDED.username)
            """,
            (from_id, username),
        )
        await conn.execute(
            """
            INSERT INTO conversations (
                external_id, agent_id, thread_id,
                last_message, last_message_at, message_count)
            VALUES (%s, %s, %s, %s, NOW(), 0)
            ON CONFLICT (external_id, agent_id) DO UPDATE SET
                last_message = EXCLUDED.last_message,
                last_message_at = NOW(),
                updated_at = NOW()
            """,
            (from_id, agent_id, thread_id, private_text),
        )
        await conn.commit()
