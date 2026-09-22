"""Métricas de negócio do painel: leads, encaminhamentos, horários e assuntos.

Tudo é calculado sobre `message_queue` (canal Instagram) no fuso da loja
(`BUSINESS_TIMEZONE`), para que "hoje" e "horário de pico" batam com o relógio
de quem está atendendo.

Definições:
- Lead novo: contato cuja PRIMEIRA mensagem (de todos os tempos) caiu no dia.
- Encaminhado à Patrícia: resposta do bot que contém o telefone dela
  (`HANDOFF_PHONE`), que o prompt manda incluir em todo encaminhamento.
- Assunto: mensagem do cliente (texto ou transcrição de áudio) que casa com
  as palavras-chave de `TOPICS`. Uma mensagem pode contar em mais de um.
"""

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import LiteralString, cast
from zoneinfo import ZoneInfo

from psycopg_pool import AsyncConnectionPool

# (chave, rótulo, regex POSIX case-insensitive). \m e \M são as bordas de
# palavra do PostgreSQL.
TOPICS: list[tuple[str, str, str]] = [
    (
        "preco",
        "Preço e desconto",
        r"pre[çc]o|valor|quanto (custa|est[áa]|fica|[ée]|sai)|desconto|promo",
    ),
    (
        "tamanho",
        "Tamanho e numeração",
        r"tamanho|numera|n[úu]mero|\m(3[4-9]|4[0-4])\M|calço|calca",
    ),
    (
        "estoque",
        "Estoque e cores",
        r"estoque|dispon[íi]vel|tem (na|em|esse|essa|o|a)|cores?\M|outra cor",
    ),
    (
        "frete",
        "Frete e entrega",
        r"frete|envi[ao]|entrega|prazo|correio|sedex|receber",
    ),
    (
        "pagamento",
        "Pagamento e parcelamento",
        r"pagamento|pix|cart[ãa]o|parcel|boleto|cr[ée]dito|d[ée]bito|sinal",
    ),
    (
        "troca",
        "Troca e devolução",
        r"troca|devol|defeito|reembolso|garantia",
    ),
    (
        "loja",
        "Endereço e horário",
        r"endere[çc]o|onde fica|hor[áa]rio|abre|fecha|localiza|loja f[íi]sica"
        r"|barro preto",
    ),
    (
        "modelos",
        "Modelos e novidades",
        r"modelo|cat[áa]logo|lan[çc]amento|novidade|foto|sand[áa]lia|sapatilha"
        r"|scarpin|salto|bota|rasteir|mocassim|t[êe]nis|anabela",
    ),
]

_NON_DIGITS = r"\D"
HANDOFF_LOOKBACK_DAYS = 7
HANDOFF_QUEUE_LIMIT = 8


def handoff_digits(phone: str) -> str:
    """Só os dígitos do telefone de encaminhamento (vazio desabilita)."""
    return re.sub(r"\D", "", phone)


def _handoff_sql(enabled: bool, prefix: str = "") -> str:
    """Condição SQL de "resposta com encaminhamento à Patrícia".

    Compara só os dígitos da resposta com o telefone configurado, então
    "31 99345-6562" e "31993456562" contam igual. Sem telefone configurado,
    nada é encaminhamento.
    """
    if not enabled:
        return "FALSE"
    return (
        f"{prefix}status = 'done' AND "
        f"regexp_replace(COALESCE({prefix}response, ''), %(nd)s, '', 'g') "
        "LIKE %(hl)s"
    )


def fill_daily(
    days: list[date],
    messages: dict[date, tuple[int, int, int, int]],
    leads: dict[date, int],
) -> list[dict]:
    """Série diária contínua (dias sem mensagem entram com zero).

    Args:
        days: Todos os dias do período, em ordem.
        messages: dia -> (mensagens, contatos, encaminhamentos, contatos
            encaminhados).
        leads: dia -> leads novos.
    """
    series = []
    for day in days:
        msgs, contacts, handoffs, handoff_contacts = messages.get(day, (0, 0, 0, 0))
        series.append(
            {
                "date": day.isoformat(),
                "messages": msgs,
                "contacts": contacts,
                "new_leads": leads.get(day, 0),
                "handoffs": handoffs,
                "handoff_contacts": handoff_contacts,
            }
        )
    return series


def _sql(query: str) -> LiteralString:
    """Marca a consulta como SQL confiável para o type checker do psycopg.

    As f-strings deste módulo interpolam só constantes (fragmentos fixos de SQL
    e nomes de coluna); todo valor variável vai por parâmetro (`%(nome)s`).
    """
    return cast(LiteralString, query)


def _pct(part: int, whole: int) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0


async def build_dashboard(
    pool: AsyncConnectionPool,
    *,
    days: int,
    timezone: str,
    handoff_phone: str,
) -> dict:
    """Monta o payload completo do dashboard para os últimos `days` dias."""
    tz = ZoneInfo(timezone)
    today = datetime.now(tz).date()
    day_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    start_date = day_list[0]
    start_ts = datetime.combine(start_date, time.min, tzinfo=tz)
    recent_ts = datetime.now(UTC) - timedelta(days=HANDOFF_LOOKBACK_DAYS)

    digits = handoff_digits(handoff_phone)
    params = {
        "tz": timezone,
        "start": start_ts,
        "start_date": start_date,
        "recent": recent_ts,
        "hl": f"%{digits}%",
        "nd": _NON_DIGITS,
    }
    handoff = _handoff_sql(bool(digits))
    handoff_m = _handoff_sql(bool(digits), "m.")
    base = "channel = 'instagram'"
    local = "created_at AT TIME ZONE %(tz)s"

    async with pool.connection() as conn:
        cur = await conn.execute(
            _sql(f"""
            SELECT ({local})::date,
                   COUNT(*),
                   COUNT(DISTINCT external_id),
                   COUNT(*) FILTER (WHERE {handoff}),
                   COUNT(DISTINCT external_id) FILTER (WHERE {handoff})
            FROM message_queue
            WHERE {base} AND created_at >= %(start)s
            GROUP BY 1
            """),
            params,
        )
        messages = {r[0]: (r[1], r[2], r[3], r[4]) for r in await cur.fetchall()}

        cur = await conn.execute(
            _sql(f"""
            SELECT first_day, COUNT(*) FROM (
                SELECT external_id,
                       (MIN(created_at) AT TIME ZONE %(tz)s)::date AS first_day
                FROM message_queue WHERE {base} GROUP BY external_id
            ) t
            WHERE first_day >= %(start_date)s
            GROUP BY 1
            """),
            params,
        )
        leads = {r[0]: r[1] for r in await cur.fetchall()}

        cur = await conn.execute(
            _sql(f"""
            SELECT COUNT(*), COUNT(DISTINCT external_id),
                   COUNT(*) FILTER (WHERE status = 'done'),
                   COUNT(*) FILTER (WHERE {handoff}),
                   COUNT(DISTINCT external_id) FILTER (WHERE {handoff}),
                   COUNT(*) FILTER (WHERE status = 'failed')
            FROM message_queue
            WHERE {base} AND created_at >= %(start)s
            """),
            params,
        )
        totals = await cur.fetchone() or (0, 0, 0, 0, 0, 0)

        cur = await conn.execute(
            _sql(f"SELECT COUNT(DISTINCT external_id) FROM message_queue WHERE {base}")
        )
        row = await cur.fetchone()
        total_contacts = row[0] if row else 0

        cur = await conn.execute(
            _sql(f"""
            SELECT EXTRACT(HOUR FROM {local})::int,
                   EXTRACT(DOW FROM {local})::int,
                   COUNT(*)
            FROM message_queue
            WHERE {base} AND created_at >= %(start)s
            GROUP BY 1, 2
            """),
            params,
        )
        by_hour = [0] * 24
        by_weekday = [0] * 7
        for hour, dow, count in await cur.fetchall():
            by_hour[hour] += count
            by_weekday[dow] += count

        cur = await conn.execute(
            _sql(f"""
            SELECT CASE WHEN media_type LIKE 'image%%' THEN 'image'
                        WHEN media_type LIKE 'audio%%' THEN 'audio'
                        ELSE 'text' END,
                   COUNT(*)
            FROM message_queue
            WHERE {base} AND created_at >= %(start)s
            GROUP BY 1
            """),
            params,
        )
        media = {"text": 0, "image": 0, "audio": 0}
        media.update({k: v for k, v in await cur.fetchall()})

        topic_params = {f"t{i}": regex for i, (_, _, regex) in enumerate(TOPICS)}
        filters = ", ".join(
            f"COUNT(*) FILTER (WHERE txt ~* %(t{i})s)" for i in range(len(TOPICS))
        )
        cur = await conn.execute(
            _sql(f"""
            SELECT {filters} FROM (
                SELECT COALESCE(NULLIF(normalized_input, ''), incoming_message, '')
                       AS txt
                FROM message_queue
                WHERE {base} AND created_at >= %(start)s
            ) q
            """),
            {**params, **topic_params},
        )
        topic_counts = await cur.fetchone() or (0,) * len(TOPICS)

        cur = await conn.execute(
            _sql(f"""
            SELECT external_id, username, name, profile_pic_url, whatsapp,
                   last_message, created_at
            FROM (
                SELECT DISTINCT ON (m.external_id)
                       m.external_id, c.username, c.name, c.profile_pic_url,
                       c.whatsapp,
                       COALESCE(NULLIF(m.normalized_input, ''), m.incoming_message)
                           AS last_message,
                       m.created_at
                FROM message_queue m
                LEFT JOIN contacts c ON c.external_id = m.external_id
                WHERE m.channel = 'instagram'
                  AND m.created_at >= %(recent)s
                  AND {handoff_m}
                ORDER BY m.external_id, m.created_at DESC
            ) t
            ORDER BY created_at DESC
            LIMIT {HANDOFF_QUEUE_LIMIT}
            """),
            params,
        )
        handoff_queue = [
            {
                "external_id": r[0],
                "username": r[1],
                "name": r[2],
                "profile_pic_url": r[3],
                "whatsapp": r[4],
                "last_message": (r[5] or "").strip(),
                "at": r[6].isoformat() if r[6] else None,
            }
            for r in await cur.fetchall()
        ]

    daily = fill_daily(day_list, messages, leads)
    msgs, contacts, done, handoff_msgs, handoff_contacts, failures = totals
    new_leads = sum(d["new_leads"] for d in daily)
    today_row = daily[-1]
    yesterday_row = daily[-2] if len(daily) > 1 else None

    return {
        "period_days": days,
        "timezone": timezone,
        "generated_at": datetime.now(UTC).isoformat(),
        "handoff_enabled": bool(digits),
        "today": today_row,
        "yesterday": yesterday_row,
        "period": {
            "messages": msgs,
            "contacts": contacts,
            "new_leads": new_leads,
            "returning_contacts": max(contacts - new_leads, 0),
            "handoff_messages": handoff_msgs,
            "handoff_contacts": handoff_contacts,
            "handoff_contact_rate": _pct(handoff_contacts, contacts),
            "ai_only_rate": round(100 - _pct(handoff_contacts, contacts), 1)
            if contacts
            else 0.0,
            "answered_messages": done,
            "failures": failures,
            "total_contacts": total_contacts,
        },
        "daily": daily,
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "media": media,
        "topics": [
            {"key": key, "label": label, "count": topic_counts[i]}
            for i, (key, label, _) in enumerate(TOPICS)
        ],
        "handoff_queue": handoff_queue,
    }
