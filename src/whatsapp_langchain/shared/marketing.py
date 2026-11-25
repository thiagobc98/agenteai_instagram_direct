"""Conversas da equipe com o agente de marketing (migration 011)."""

from __future__ import annotations

import json
from datetime import datetime

from psycopg_pool import AsyncConnectionPool


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def create_thread(
    pool: AsyncConnectionPool, *, title: str, created_by: str
) -> dict:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO marketing_threads (title, created_by) VALUES (%s, %s)
            RETURNING id, title, created_by, created_at, updated_at
            """,
            (title[:120], created_by),
        )
        row = await cursor.fetchone()
        await conn.commit()
    return _thread_row(row)


def _thread_row(row: tuple) -> dict:
    return {
        "id": row[0],
        "title": row[1],
        "created_by": row[2],
        "created_at": _iso(row[3]),
        "updated_at": _iso(row[4]),
    }


async def list_threads(pool: AsyncConnectionPool, limit: int = 50) -> list[dict]:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, title, created_by, created_at, updated_at
            FROM marketing_threads ORDER BY updated_at DESC LIMIT %s
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    return [_thread_row(r) for r in rows]


async def get_thread(pool: AsyncConnectionPool, thread_id: int) -> dict | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, title, created_by, created_at, updated_at
            FROM marketing_threads WHERE id = %s
            """,
            (thread_id,),
        )
        row = await cursor.fetchone()
    return _thread_row(row) if row else None


async def delete_thread(pool: AsyncConnectionPool, thread_id: int) -> bool:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "DELETE FROM marketing_threads WHERE id = %s RETURNING id", (thread_id,)
        )
        deleted = await cursor.fetchone() is not None
        await conn.commit()
    return deleted


async def list_messages(
    pool: AsyncConnectionPool, thread_id: int, limit: int = 200
) -> list[dict]:
    """Mensagens da conversa, mais antigas primeiro."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, role, content, actions, created_by, created_at FROM (
                SELECT * FROM marketing_messages WHERE thread_id = %s
                ORDER BY id DESC LIMIT %s
            ) recent ORDER BY id
            """,
            (thread_id, limit),
        )
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "role": r[1],
            "content": r[2],
            "actions": r[3] if isinstance(r[3], list) else json.loads(r[3] or "[]"),
            "created_by": r[4],
            "created_at": _iso(r[5]),
        }
        for r in rows
    ]


async def add_message(
    pool: AsyncConnectionPool,
    thread_id: int,
    *,
    role: str,
    content: str,
    actions: list[dict] | None = None,
    created_by: str | None = None,
) -> dict:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO marketing_messages
                (thread_id, role, content, actions, created_by)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            RETURNING id, created_at
            """,
            (thread_id, role, content, json.dumps(actions or []), created_by),
        )
        row = await cursor.fetchone()
        await conn.execute(
            "UPDATE marketing_threads SET updated_at = NOW() WHERE id = %s",
            (thread_id,),
        )
        await conn.commit()
    return {
        "id": row[0],
        "role": role,
        "content": content,
        "actions": actions or [],
        "created_by": created_by,
        "created_at": _iso(row[1]),
    }
