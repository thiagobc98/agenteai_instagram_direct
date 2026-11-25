"""Ferramentas do agente de marketing.

Criadas por requisição (`build_tools`), presas ao contexto de quem está
conversando no painel: pool do banco, cliente da Graph API e a lista de
ações (rascunhos criados) que volta para o painel.

Princípio: toda conta é feita aqui, em Python (médias, taxas, melhor
horário). O modelo só interpreta. LLM erra aritmética e "arredonda" dados.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

import structlog
from langchain_core.tools import BaseTool, tool
from psycopg_pool import AsyncConnectionPool

from whatsapp_langchain.agents.captions.generator import BRAND_HASHTAG
from whatsapp_langchain.shared import publishing as pub_store
from whatsapp_langchain.shared.analytics import build_dashboard
from whatsapp_langchain.shared.comments import list_comments
from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.shared.marketing_calendar import upcoming_dates
from whatsapp_langchain.worker.instagram_client import (
    InstagramClient,
    InstagramSendError,
)

logger = structlog.get_logger()

WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MAX_DRAFTS_PER_TURN = 10
MAX_SCHEDULE_DAYS = 75
_PRICE = re.compile(r"R\$\s*\d|\d+\s*reais", re.IGNORECASE)

# Cache das métricas por post (a Meta limita chamadas; métricas mudam devagar)
_INSIGHTS_TTL_SECONDS = 15 * 60
_insights_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class MarketingContext:
    pool: AsyncConnectionPool
    instagram: InstagramClient | None
    created_by: str
    actions: list[dict] = field(default_factory=list)

    @property
    def drafts_created(self) -> int:
        return sum(1 for a in self.actions if a.get("type") == "draft")


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.business_timezone)


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _unavailable(what: str, exc: Exception) -> str:
    if isinstance(exc, InstagramSendError):
        if exc.is_token_invalid:
            reason = "o token do Instagram expirou ou é inválido"
        elif exc.code in (10, 200):
            reason = "o token não tem a permissão instagram_business_manage_insights"
        else:
            reason = f"a Meta recusou ({exc.detail[:120]})"
    else:
        reason = f"erro de conexão ({str(exc)[:120]})"
    return _json({"indisponivel": True, "dado": what, "motivo": reason})


# ---------------------------------------------------------------------------
# Agregações (puras, testadas)
# ---------------------------------------------------------------------------


def _rate(part: int | None, whole: int | None) -> float | None:
    if not part or not whole:
        return None
    return round(100 * part / whole, 2)


def post_row(media: dict, insights: dict, tz: ZoneInfo) -> dict:
    """Uma linha por post, com taxas já calculadas."""
    ts = media.get("timestamp")
    when = None
    if isinstance(ts, str):
        try:
            when = datetime.fromisoformat(ts.replace("+0000", "+00:00")).astimezone(tz)
        except ValueError:
            when = None
    product = (media.get("media_product_type") or "").upper()
    kind = (
        "reels"
        if product == "REELS"
        else (
            "carrossel"
            if media.get("media_type") == "CAROUSEL_ALBUM"
            else "foto"
            if media.get("media_type") == "IMAGE"
            else "video"
        )
    )
    likes = insights.get("likes", media.get("like_count"))
    comments = insights.get("comments", media.get("comments_count"))
    reach = insights.get("reach")
    saved = insights.get("saved")
    shares = insights.get("shares")
    interactions = sum(
        v for v in (likes, comments, saved, shares) if isinstance(v, int)
    )
    return {
        "id": media.get("id"),
        "formato": kind,
        "data": when.strftime("%d/%m/%Y") if when else None,
        "dia_semana": WEEKDAYS[when.weekday()] if when else None,
        "hora": when.hour if when else None,
        "legenda": (media.get("caption") or "")[:90],
        "link": media.get("permalink"),
        "alcance": reach,
        "visualizacoes": insights.get("views"),
        "curtidas": likes,
        "comentarios": comments,
        "salvamentos": saved,
        "compartilhamentos": shares,
        "taxa_engajamento_pct": _rate(interactions, reach),
        "taxa_salvamento_pct": _rate(saved, reach),
    }


def summarize_posts(rows: list[dict]) -> dict:
    """Médias por formato e por faixa de horário (só com o que existe)."""

    def avg(items: list[dict], key: str) -> float | None:
        values = [r[key] for r in items if isinstance(r.get(key), int | float)]
        return round(mean(values), 1) if values else None

    by_format = {}
    for fmt in sorted({r["formato"] for r in rows}):
        items = [r for r in rows if r["formato"] == fmt]
        by_format[fmt] = {
            "posts": len(items),
            "alcance_medio": avg(items, "alcance"),
            "salvamentos_medio": avg(items, "salvamentos"),
            "compartilhamentos_medio": avg(items, "compartilhamentos"),
            "taxa_engajamento_media_pct": avg(items, "taxa_engajamento_pct"),
        }

    def bucket(hour: int) -> str:
        if hour < 12:
            return "manhã (até 12h)"
        if hour < 18:
            return "tarde (12h-18h)"
        return "noite (depois das 18h)"

    by_time = {}
    for label in ("manhã (até 12h)", "tarde (12h-18h)", "noite (depois das 18h)"):
        items = [
            r for r in rows if r["hora"] is not None and bucket(r["hora"]) == label
        ]
        if items:
            by_time[label] = {
                "posts": len(items),
                "alcance_medio": avg(items, "alcance"),
                "taxa_engajamento_media_pct": avg(items, "taxa_engajamento_pct"),
            }

    ranked = [r for r in rows if isinstance(r.get("alcance"), int)]
    ranked.sort(key=lambda r: r["alcance"], reverse=True)
    return {
        "total_posts_analisados": len(rows),
        "com_metricas": len(ranked),
        "por_formato": by_format,
        "por_horario_de_publicacao": by_time,
        "top_3_por_alcance": [r["id"] for r in ranked[:3]],
        "aviso": (
            "Amostra pequena: trate como indício, não conclusão."
            if len(ranked) < 8
            else None
        ),
    }


def with_brand_hashtag(caption: str) -> str:
    """Garante a hashtag da marca na legenda (regra de marca, não do modelo)."""
    if not caption or BRAND_HASHTAG in caption.lower():
        return caption
    return f"{caption.rstrip()} {BRAND_HASHTAG}"


def peak_hours(by_hour: list[int], top: int = 3) -> list[str]:
    ranked = sorted(range(len(by_hour)), key=lambda h: by_hour[h], reverse=True)
    return [f"{h}h ({by_hour[h]} msgs)" for h in ranked[:top] if by_hour[h] > 0]


def validate_draft(
    kind: str, caption: str, planned_for: datetime, now: datetime
) -> str | None:
    """Erro (para o modelo corrigir) ou None."""
    if kind not in pub_store.KINDS:
        return "tipo deve ser feed, story ou reels"
    if planned_for <= now:
        return "a data sugerida precisa estar no futuro"
    if planned_for > now + timedelta(days=MAX_SCHEDULE_DAYS):
        return f"sugira datas em até {MAX_SCHEDULE_DAYS} dias"
    if _PRICE.search(caption):
        return (
            "a legenda cita preço: você não sabe preços. Tire o valor ou "
            "use só o que a equipe informou na conversa (e então diga isso no briefing)"
        )
    if len(caption) > pub_store.MAX_CAPTION_CHARS:
        return "legenda passa de 2200 caracteres"
    if pub_store.count_hashtags(caption) > pub_store.MAX_HASHTAGS:
        return "máximo de 30 hashtags"
    return None


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------


async def _insights(instagram: InstagramClient, media: dict) -> dict:
    media_id = str(media.get("id"))
    cached = _insights_cache.get(media_id)
    if cached and time.monotonic() - cached[0] < _INSIGHTS_TTL_SECONDS:
        return cached[1]
    values = await instagram.media_insights(media_id, media.get("media_product_type"))
    _insights_cache[media_id] = (time.monotonic(), values)
    return values


def build_tools(ctx: MarketingContext) -> list[BaseTool]:
    tz = _tz()

    @tool
    async def ver_desempenho_dos_posts(quantidade: int = 12) -> str:
        """Desempenho dos posts recentes do feed/Reels (alcance, salvamentos,
        compartilhamentos, comentários), com médias por formato e por horário.

        Args:
            quantidade: Quantos posts recentes analisar (1 a 25).
        """
        if ctx.instagram is None:
            return _json({"indisponivel": True, "motivo": "Instagram não configurado"})
        n = max(1, min(int(quantidade), 25))
        try:
            media = await ctx.instagram.list_media(limit=n)
        except Exception as exc:
            return _unavailable("lista de posts", exc)

        # O 1º post testa a permissão de métricas; os demais vão em paralelo
        # (até 5 por vez, para respeitar o rate limit da Meta).
        insights_missing = None
        all_insights: list[dict] = [{} for _ in media]
        if media:
            try:
                all_insights[0] = await _insights(ctx.instagram, media[0])
            except Exception as exc:
                # Sem permissão de insights: segue só com curtidas/comentários
                insights_missing = json.loads(_unavailable("métricas", exc))["motivo"]
        if media and insights_missing is None:
            semaphore = asyncio.Semaphore(5)

            async def fetch(item: dict) -> dict:
                async with semaphore:
                    try:
                        return await _insights(ctx.instagram, item)
                    except Exception:
                        return {}

            all_insights[1:] = await asyncio.gather(*(fetch(m) for m in media[1:]))
        rows = [post_row(m, i, tz) for m, i in zip(media, all_insights, strict=True)]

        result = {"resumo": summarize_posts(rows), "posts": rows}
        if insights_missing:
            result["metricas_indisponiveis"] = (
                f"Alcance/salvamentos indisponíveis: {insights_missing}. "
                "Só há curtidas e comentários."
            )
        return _json(result)

    @tool
    async def ver_perfil_da_conta() -> str:
        """Seguidores, contas seguidas e total de posts do perfil da loja."""
        if ctx.instagram is None:
            return _json({"indisponivel": True, "motivo": "Instagram não configurado"})
        try:
            profile = await ctx.instagram.get_account_profile()
        except Exception as exc:
            return _unavailable("perfil", exc)
        return _json(
            {
                "usuario": profile.get("username"),
                "seguidores": profile.get("followers_count"),
                "seguindo": profile.get("follows_count"),
                "posts": profile.get("media_count"),
            }
        )

    @tool
    async def ver_demanda_das_clientes(dias: int = 30) -> str:
        """O que as clientes perguntam no Direct (assuntos), horários e dias de
        pico, leads novos, encaminhamentos para venda e comentários recentes.

        Args:
            dias: Janela de análise em dias (7 a 90).
        """
        d = max(7, min(int(dias), 90))
        try:
            dash = await build_dashboard(
                ctx.pool,
                days=d,
                timezone=settings.business_timezone,
                handoff_phone=settings.handoff_phone,
            )
            recent = await list_comments(ctx.pool, statuses=None, limit=500)
        except Exception as exc:
            return _unavailable("demanda", exc)

        period = dash["period"]
        texts = [
            c["text"] for c in recent if c["text"] and c["status"] not in ("ignored",)
        ][-30:]
        weekday = dash["by_weekday"]
        return _json(
            {
                "janela_dias": d,
                "mensagens_no_direct": period["messages"],
                "contatos": period["contacts"],
                "leads_novos": period["new_leads"],
                "encaminhadas_para_venda": period["handoff_contacts"],
                "assuntos_mais_perguntados": [
                    {"assunto": t["label"], "mensagens": t["count"]}
                    for t in sorted(
                        dash["topics"], key=lambda t: t["count"], reverse=True
                    )
                    if t["count"]
                ],
                "horarios_de_pico_no_direct": peak_hours(dash["by_hour"]),
                "mensagens_por_dia_da_semana": {
                    WEEKDAYS[i]: weekday[i] for i in range(min(7, len(weekday)))
                },
                "comentarios_recentes_nos_posts": texts,
            }
        )

    @tool
    async def ver_calendario_de_conteudo(
        dias_atras: int = 14, dias_a_frente: int = 30
    ) -> str:
        """Publicações já feitas, agendadas e rascunhos (pelo painel) no período.

        Args:
            dias_atras: Quantos dias para trás olhar.
            dias_a_frente: Quantos dias para frente olhar.
        """
        now = datetime.now(UTC)
        items = await pub_store.content_calendar(
            ctx.pool,
            since=now - timedelta(days=max(0, min(int(dias_atras), 90))),
            until=now + timedelta(days=max(0, min(int(dias_a_frente), 90))),
        )
        for it in items:
            it["caption"] = (it["caption"] or "")[:80]
            it["brief"] = (it["brief"] or "")[:120]
        return _json(
            {
                "observacao": "Só inclui o que passou pelo painel (posts feitos "
                "direto no app do Instagram aparecem em ver_desempenho_dos_posts).",
                "itens": items,
            }
        )

    @tool
    async def ver_datas_comerciais(dias_a_frente: int = 75) -> str:
        """Próximas datas comerciais do varejo, com quando começar a campanha.

        Args:
            dias_a_frente: Horizonte em dias (até 120).
        """
        today = datetime.now(tz).date()
        found = upcoming_dates(today, max(7, min(int(dias_a_frente), 120)))
        return _json(
            [
                {
                    "data": d.day.strftime("%d/%m/%Y"),
                    "dia_semana": WEEKDAYS[d.day.weekday()],
                    "nome": d.name,
                    "faltam_dias": (d.day - today).days,
                    "comecar_campanha_em": max(
                        today, d.day - timedelta(days=d.prep_days)
                    ).strftime("%d/%m/%Y"),
                    "por_que_importa": d.note,
                }
                for d in found
            ]
        )

    @tool
    async def criar_rascunho_de_post(
        tipo: str,
        briefing: str,
        legenda: str,
        data_sugerida: str,
        justificativa: str,
    ) -> str:
        """Cria um rascunho na tela Publicar. A equipe sobe a mídia e aprova;
        nada é publicado sem aprovação.

        Args:
            tipo: "feed", "story" ou "reels".
            briefing: Instruções para quem vai fotografar/filmar: o que mostrar,
                enquadramento, formato (9:16 ou 4:5), duração, texto na arte.
            legenda: Legenda pronta, texto puro, com chamada para ação e
                hashtags. Vazia para story.
            data_sugerida: Data e hora no formato AAAA-MM-DDTHH:MM (horário de
                Brasília).
            justificativa: Por que este post, neste dia e horário (cite o dado).
        """
        if ctx.drafts_created >= MAX_DRAFTS_PER_TURN:
            return f"Limite de {MAX_DRAFTS_PER_TURN} rascunhos por resposta atingido."
        kind = tipo.strip().lower()
        try:
            planned = datetime.fromisoformat(data_sugerida.strip())
        except ValueError:
            return "data_sugerida inválida: use AAAA-MM-DDTHH:MM"
        if planned.tzinfo is None:
            planned = planned.replace(tzinfo=tz)
        caption = "" if kind == "story" else with_brand_hashtag(legenda.strip())
        error = validate_draft(kind, caption, planned, datetime.now(tz))
        if error:
            return f"Rascunho NÃO criado: {error}. Corrija e tente de novo."

        pub_id = await pub_store.create_suggested_draft(
            ctx.pool,
            kind=kind,
            brief=briefing.strip()[:4000],
            caption=caption,
            planned_for=planned,
            rationale=justificativa.strip()[:1000],
            created_by=f"agente-marketing ({ctx.created_by})",
        )
        ctx.actions.append(
            {
                "type": "draft",
                "publication_id": pub_id,
                "kind": kind,
                "planned_for": planned.isoformat(),
                "title": (briefing.strip().split("\n")[0])[:90],
            }
        )
        logger.info("marketing_draft_created", pub_id=pub_id, kind=kind)
        return _json(
            {"criado": True, "id": pub_id, "tipo": kind, "data": planned.isoformat()}
        )

    return [
        ver_desempenho_dos_posts,
        ver_perfil_da_conta,
        ver_demanda_das_clientes,
        ver_calendario_de_conteudo,
        ver_datas_comerciais,
        criar_rascunho_de_post,
    ]
