"""Perfis dos contatos do Instagram (@username, nome, foto).

Tabela `contacts` (migration 007). Preenchida pelo Worker a partir da User
Profile API; lida pelo painel administrativo.
"""

import structlog
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

# Contato com @ conhecido: renova a cada 7 dias (o @ e a foto podem mudar).
REFRESH_DAYS = 7
# Contato sem @ (falha anterior ou perfil sem username): tenta de novo a cada hora.
RETRY_MINUTES = 60


async def upsert_contact(
    pool: AsyncConnectionPool,
    external_id: str,
    *,
    username: str | None,
    name: str | None,
    profile_pic_url: str | None,
) -> None:
    """Cria ou atualiza o perfil de um contato."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO contacts (external_id, username, name, profile_pic_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (external_id) DO UPDATE SET
                username = EXCLUDED.username,
                name = EXCLUDED.name,
                profile_pic_url = EXCLUDED.profile_pic_url,
                fetched_at = NOW()
            """,
            (external_id, username, name, profile_pic_url),
        )
        await conn.commit()


async def get_contact_username(
    pool: AsyncConnectionPool, external_id: str
) -> str | None:
    """@username salvo do contato, se o perfil já foi buscado.

    Usado pelo Worker para mencionar a cliente pelo @ na saudação (ver
    `agents/middleware/greeting.py`). None quando o contato ainda não tem
    perfil salvo ou o perfil não tinha username.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT username FROM contacts WHERE external_id = %s",
            (external_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def needs_profile_refresh(pool: AsyncConnectionPool, external_id: str) -> bool:
    """True se o contato não tem perfil salvo ou o perfil está desatualizado."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT NOT EXISTS (SELECT 1 FROM contacts WHERE external_id = %(id)s)
                OR EXISTS (
                    SELECT 1 FROM contacts
                    WHERE external_id = %(id)s
                      AND fetched_at < NOW() - CASE
                          WHEN username IS NOT NULL
                              THEN make_interval(days => %(days)s)
                          ELSE make_interval(mins => %(mins)s)
                      END
                )
            """,
            {"id": external_id, "days": REFRESH_DAYS, "mins": RETRY_MINUTES},
        )
        row = await cursor.fetchone()
        return bool(row and row[0])


async def list_contacts_without_profile(
    pool: AsyncConnectionPool, limit: int = 200
) -> list[str]:
    """IGSIDs que já conversaram mas ainda não têm @ salvo."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT DISTINCT m.external_id
            FROM message_queue m
            LEFT JOIN contacts c ON c.external_id = m.external_id
            WHERE m.channel = 'instagram' AND c.username IS NULL
            LIMIT %s
            """,
            (limit,),
        )
        return [row[0] for row in await cursor.fetchall()]
