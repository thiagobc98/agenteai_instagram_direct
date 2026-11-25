"""Avisos no WhatsApp do atendente a cada mensagem nova do Direct.

Migration 012. Quem escreve aqui:
- Webhook do Instagram: `enqueue_notification` (um aviso por mensagem).
- Worker (`worker/notifier.py`): `claim_batch` + `mark_*` (envio pelo Wuzapi).
- Painel (`server/routes/whatsapp_notify.py`): configurações e histórico.

Mensagens seguidas da mesma cliente saem juntas em um aviso: cada aviso novo
empurra o horário de envio dos pendentes dela (debounce), com teto, para o
atendente não receber 5 avisos para 5 mensagens digitadas em 10 segundos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.shared.contacts import normalize_whatsapp

# Espera depois da última mensagem da cliente antes de avisar (junta rajadas)
DEBOUNCE_SECONDS = 4
# Teto da espera: mesmo com a cliente digitando sem parar, avisa depois disso
MAX_DEBOUNCE_SECONDS = 20
# Lease de quem está enviando (crash no meio: volta para a fila depois disso)
SENDING_LEASE_SECONDS = 60
# Novas tentativas: 30s, 1min, 2min, 4min, 8min, 16min
MAX_ATTEMPTS = 6
RETRY_BASE_SECONDS = 30
# Aviso que não saiu em 6h (WhatsApp desconectado) já não ajuda: descarta
MAX_AGE_HOURS = 6
# Trecho da mensagem da cliente no aviso
PREVIEW_CHARS = 300

# Chave: tipo do anexo do Instagram ("image/*" -> image,
# "unsupported/ig_reel" -> ig_reel; ver shared/instagram_payload.py)
MEDIA_LABEL = {
    "image": "📷 foto",
    "audio": "🎤 áudio",
    "video": "🎥 vídeo",
    "file": "📎 arquivo",
    "share": "🔗 post compartilhado",
    "ig_reel": "🎬 reels compartilhado",
    "reel": "🎬 reels compartilhado",
    "story_mention": "📣 menção no story",
    "story_reply": "💬 resposta ao story",
}


def _media_key(media_type: str) -> str:
    kind, _, rest = media_type.partition("/")
    return rest if kind == "unsupported" else kind


@dataclass(frozen=True)
class NotifySettings:
    enabled: bool
    recipients: list[str]
    updated_by: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class PendingNotification:
    id: int
    external_id: str
    body: str
    media_type: str | None
    attempts: int
    created_at: datetime


def retry_delay_seconds(attempts: int) -> int:
    return RETRY_BASE_SECONDS * 2 ** max(attempts - 1, 0)


def normalize_recipients(raw: list[str]) -> tuple[list[str], list[str]]:
    """(números válidos sem repetição, entradas inválidas)."""
    valid: list[str] = []
    invalid: list[str] = []
    for item in raw:
        if not item.strip():
            continue
        number = normalize_whatsapp(item)
        if number is None:
            invalid.append(item.strip())
        elif number not in valid:
            valid.append(number)
    return valid, invalid


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def message_preview(body: str, media_type: str | None) -> str:
    text = _clip(body or "", PREVIEW_CHARS)
    label = ""
    if media_type:
        key = _media_key(media_type)
        label = MEDIA_LABEL.get(key, f"📎 {key or 'anexo'}")
    if label and text:
        return f"{label}: {text}"
    return text or label or "(mensagem sem texto)"


def format_notification(
    items: list[PendingNotification],
    *,
    username: str | None,
    name: str | None,
    panel_url: str | None,
) -> str:
    """Texto do aviso (formatação do WhatsApp: *negrito*, _itálico_)."""
    who = f"@{username}" if username else (name or "Cliente sem @")
    if name and username:
        who = f"{who} ({name})"
    lines = ["📩 *Nova mensagem no Direct*", f"*{who}*", ""]
    if len(items) == 1:
        lines.append(message_preview(items[0].body, items[0].media_type))
    else:
        lines.append(f"_{len(items)} mensagens:_")
        lines += [f"• {message_preview(i.body, i.media_type)}" for i in items[:8]]
        if len(items) > 8:
            lines.append(f"• … e mais {len(items) - 8}")
    lines.append("")
    if username:
        lines.append(f"Abrir no Instagram: https://ig.me/m/{username}")
    if panel_url:
        lines.append(f"Ver no painel: {panel_url}")
    return "\n".join(lines).strip()


# --- Banco ---------------------------------------------------------------------


async def get_settings(pool: AsyncConnectionPool) -> NotifySettings:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT enabled, recipients, updated_by, updated_at
            FROM attendant_notify_settings WHERE id = 1
            """
        )
        row = await cursor.fetchone()
    if not row:
        return NotifySettings(True, [], None, None)
    return NotifySettings(row[0], list(row[1] or []), row[2], row[3])


async def save_settings(
    pool: AsyncConnectionPool,
    *,
    enabled: bool,
    recipients: list[str],
    updated_by: str,
) -> NotifySettings:
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO attendant_notify_settings (id, enabled, recipients, updated_by)
            VALUES (1, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                recipients = EXCLUDED.recipients,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (enabled, recipients, updated_by),
        )
        await conn.commit()
    return await get_settings(pool)


async def enqueue_notification(
    pool: AsyncConnectionPool,
    *,
    external_id: str,
    body: str,
    media_type: str | None,
    source_message_id: str | None,
) -> bool:
    """Grava o aviso de uma mensagem recebida. False se já existia (a Meta
    reenviou o webhook). Adia os avisos pendentes da mesma cliente para saírem
    todos juntos."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO attendant_notifications
                (external_id, body, media_type, source_message_id, next_attempt_at)
            VALUES (%s, %s, %s, %s, NOW() + make_interval(secs => %s))
            ON CONFLICT (source_message_id) DO NOTHING
            RETURNING id
            """,
            (external_id, body or "", media_type, source_message_id, DEBOUNCE_SECONDS),
        )
        created = await cursor.fetchone() is not None
        if created:
            await conn.execute(
                """
                UPDATE attendant_notifications SET next_attempt_at = LEAST(
                    NOW() + make_interval(secs => %s),
                    created_at + make_interval(secs => %s))
                WHERE external_id = %s AND status = 'pending' AND attempts = 0
                """,
                (DEBOUNCE_SECONDS, MAX_DEBOUNCE_SECONDS, external_id),
            )
        await conn.commit()
    return created


async def skip_stale(pool: AsyncConnectionPool) -> int:
    """Descarta avisos antigos demais para ainda ajudarem."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            UPDATE attendant_notifications
            SET status = 'skipped', error = 'antigo demais para avisar'
            WHERE status IN ('pending', 'sending')
              AND created_at < NOW() - make_interval(hours => %s)
            """,
            (MAX_AGE_HOURS,),
        )
        await conn.commit()
        return cursor.rowcount or 0


async def claim_batch(pool: AsyncConnectionPool) -> list[PendingNotification]:
    """Pega os avisos vencidos da cliente mais antiga na fila (todos juntos)."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            WITH first AS (
                SELECT external_id FROM attendant_notifications
                WHERE status IN ('pending', 'sending') AND next_attempt_at <= NOW()
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE attendant_notifications n
            SET status = 'sending',
                next_attempt_at = NOW() + make_interval(secs => %s)
            FROM first
            WHERE n.external_id = first.external_id
              AND n.status IN ('pending', 'sending')
              AND n.next_attempt_at <= NOW()
            RETURNING n.id, n.external_id, n.body, n.media_type, n.attempts,
                      n.created_at
            """,
            (SENDING_LEASE_SECONDS,),
        )
        rows = await cursor.fetchall()
        await conn.commit()
    items = [PendingNotification(*row) for row in rows]
    return sorted(items, key=lambda i: i.created_at)


async def mark_sent(
    pool: AsyncConnectionPool, ids: list[int], error: str | None
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE attendant_notifications
            SET status = 'sent', sent_at = NOW(), attempts = attempts + 1, error = %s
            WHERE id = ANY(%s)
            """,
            (error, ids),
        )
        await conn.commit()


async def mark_skipped(pool: AsyncConnectionPool, ids: list[int], reason: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE attendant_notifications SET status = 'skipped', error = %s "
            "WHERE id = ANY(%s)",
            (reason, ids),
        )
        await conn.commit()


async def mark_failed(
    pool: AsyncConnectionPool, items: list[PendingNotification], error: str
) -> bool:
    """Agenda nova tentativa ou desiste. True se desistiu."""
    attempts = max(i.attempts for i in items) + 1
    give_up = attempts >= MAX_ATTEMPTS
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE attendant_notifications
            SET status = %s, attempts = %s, error = %s,
                next_attempt_at = NOW() + make_interval(secs => %s)
            WHERE id = ANY(%s)
            """,
            (
                "failed" if give_up else "pending",
                attempts,
                error[:500],
                retry_delay_seconds(attempts),
                [i.id for i in items],
            ),
        )
        await conn.commit()
    return give_up


async def list_recent(pool: AsyncConnectionPool, limit: int = 20) -> list[dict]:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT n.id, n.external_id, c.username, n.body, n.media_type, n.status,
                   n.attempts, n.error, n.created_at, n.sent_at
            FROM attendant_notifications n
            LEFT JOIN contacts c ON c.external_id = n.external_id
            ORDER BY n.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "external_id": r[1],
            "username": r[2],
            "preview": message_preview(r[3], r[4]),
            "status": r[5],
            "attempts": r[6],
            "error": r[7],
            "created_at": r[8].isoformat() if r[8] else None,
            "sent_at": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]
