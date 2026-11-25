"""Testes do agente de marketing: calendário comercial, agregações das
métricas, ferramentas (travas e degradação sem permissão) e rotas."""

import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from whatsapp_langchain.agents.marketing import agent as agent_mod
from whatsapp_langchain.agents.marketing import tools as tools_mod
from whatsapp_langchain.agents.marketing.agent import build_messages, today_line
from whatsapp_langchain.agents.marketing.tools import (
    MarketingContext,
    build_tools,
    peak_hours,
    post_row,
    summarize_posts,
    validate_draft,
)
from whatsapp_langchain.server.main import app
from whatsapp_langchain.shared.marketing_calendar import (
    black_friday,
    easter,
    nth_weekday,
    upcoming_dates,
)
from whatsapp_langchain.worker.instagram_client import InstagramSendError

TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# Calendário comercial
# ---------------------------------------------------------------------------


class TestCalendar:
    @pytest.mark.parametrize(
        ("year", "expected"),
        [
            (2024, date(2024, 3, 31)),
            (2026, date(2026, 4, 5)),
            (2027, date(2027, 3, 28)),
        ],
    )
    def test_easter(self, year, expected):
        assert easter(year) == expected

    def test_mothers_day_second_sunday_of_may(self):
        assert nth_weekday(2026, 5, 6, 2) == date(2026, 5, 10)
        assert nth_weekday(2027, 5, 6, 2) == date(2027, 5, 9)

    def test_black_friday(self):
        assert black_friday(2025) == date(2025, 11, 28)
        assert black_friday(2026) == date(2026, 11, 27)

    def test_upcoming_crosses_year(self):
        names = [d.name for d in upcoming_dates(date(2026, 11, 24), 90)]
        assert names[0] == "Black Friday"
        assert "Natal" in names and "Réveillon" in names
        assert "Liquidação de verão" in names  # janeiro de 2027
        assert "Carnaval" in names  # 09/02/2027

    def test_carnival_2027(self):
        carnaval = next(
            d for d in upcoming_dates(date(2027, 1, 1), 60) if d.name == "Carnaval"
        )
        assert carnaval.day == date(2027, 2, 9)


# ---------------------------------------------------------------------------
# Agregações
# ---------------------------------------------------------------------------


def media(i, product="FEED", media_type="IMAGE", hour=19):
    return {
        "id": f"M{i}",
        "media_type": media_type,
        "media_product_type": product,
        "timestamp": f"2026-11-1{i}T{hour - (-3):02d}:00:00+0000",  # UTC = BRT+3
        "caption": f"Post {i}",
        "like_count": 10,
        "comments_count": 2,
    }


class TestAggregation:
    def test_post_row_rates_and_local_time(self):
        row = post_row(
            media(1),
            {"reach": 1000, "likes": 50, "comments": 5, "saved": 20, "shares": 25},
            TZ,
        )
        assert row["formato"] == "foto"
        assert row["hora"] == 19  # convertido para Brasília
        assert row["taxa_engajamento_pct"] == 10.0
        assert row["taxa_salvamento_pct"] == 2.0

    def test_post_row_without_insights_uses_counts(self):
        row = post_row(media(1), {}, TZ)
        assert row["curtidas"] == 10
        assert row["alcance"] is None
        assert row["taxa_engajamento_pct"] is None

    def test_formats(self):
        assert post_row(media(1, "REELS", "VIDEO"), {}, TZ)["formato"] == "reels"
        assert (
            post_row(media(1, "FEED", "CAROUSEL_ALBUM"), {}, TZ)["formato"]
            == "carrossel"
        )

    def test_summary_by_format_and_time(self):
        rows = [
            post_row(media(1, "REELS", "VIDEO", 19), {"reach": 3000, "saved": 30}, TZ),
            post_row(media(2, "REELS", "VIDEO", 9), {"reach": 1000, "saved": 10}, TZ),
            post_row(media(3, "FEED", "IMAGE", 19), {"reach": 500, "saved": 5}, TZ),
        ]
        s = summarize_posts(rows)
        assert s["por_formato"]["reels"]["alcance_medio"] == 2000.0
        assert s["por_formato"]["foto"]["posts"] == 1
        assert s["por_horario_de_publicacao"]["noite (depois das 18h)"]["posts"] == 2
        assert s["top_3_por_alcance"] == ["M1", "M2", "M3"]
        assert "Amostra pequena" in s["aviso"]

    def test_peak_hours(self):
        by_hour = [0] * 24
        by_hour[20], by_hour[12], by_hour[9] = 30, 20, 10
        assert peak_hours(by_hour) == ["20h (30 msgs)", "12h (20 msgs)", "9h (10 msgs)"]
        assert peak_hours([0] * 24) == []


class TestBrandHashtag:
    def test_appends_when_missing(self):
        assert tools_mod.with_brand_hashtag("Vem provar! #modabh") == (
            "Vem provar! #modabh #patriciaberberich"
        )

    def test_keeps_existing_any_case(self):
        text = "Vem provar! #PatriciaBerberich"
        assert tools_mod.with_brand_hashtag(text) == text

    def test_empty_stays_empty(self):
        assert tools_mod.with_brand_hashtag("") == ""


class TestValidateDraft:
    now = datetime(2026, 11, 24, 10, tzinfo=TZ)

    def test_ok(self):
        assert (
            validate_draft("reels", "Legenda", self.now + timedelta(days=2), self.now)
            is None
        )

    def test_rejects(self):
        later = self.now + timedelta(days=2)
        assert validate_draft("tiktok", "", later, self.now)
        assert validate_draft("feed", "x", self.now - timedelta(hours=1), self.now)
        assert validate_draft("feed", "x", self.now + timedelta(days=100), self.now)
        assert "preço" in validate_draft("feed", "Só R$ 199!", later, self.now)
        assert validate_draft("feed", "a" * 2201, later, self.now)


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------


def tool_by_name(ctx, name):
    return next(t for t in build_tools(ctx) if t.name == name)


@pytest.fixture(autouse=True)
def clear_cache():
    tools_mod._insights_cache.clear()


class TestTools:
    async def test_performance_degrades_without_insights_permission(self):
        ig = AsyncMock()
        ig.list_media.return_value = [media(1), media(2)]
        ig.media_insights.side_effect = InstagramSendError(400, "no perm", code=10)
        ctx = MarketingContext(pool=object(), instagram=ig, created_by="admin")
        out = json.loads(
            await tool_by_name(ctx, "ver_desempenho_dos_posts").ainvoke({})
        )
        assert "instagram_business_manage_insights" in out["metricas_indisponiveis"]
        assert len(out["posts"]) == 2
        assert ig.media_insights.await_count == 1  # não insiste post a post

    async def test_performance_with_insights(self):
        ig = AsyncMock()
        ig.list_media.return_value = [media(1), media(2)]
        ig.media_insights.return_value = {"reach": 100, "saved": 3}
        ctx = MarketingContext(pool=object(), instagram=ig, created_by="admin")
        out = json.loads(
            await tool_by_name(ctx, "ver_desempenho_dos_posts").ainvoke(
                {"quantidade": 2}
            )
        )
        assert "metricas_indisponiveis" not in out
        assert out["resumo"]["com_metricas"] == 2

    async def test_profile_token_expired_is_explicit(self):
        ig = AsyncMock()
        ig.get_account_profile.side_effect = InstagramSendError(401, "x", code=190)
        ctx = MarketingContext(pool=object(), instagram=ig, created_by="admin")
        out = json.loads(await tool_by_name(ctx, "ver_perfil_da_conta").ainvoke({}))
        assert out["indisponivel"] is True
        assert "token" in out["motivo"]

    async def test_commercial_dates_tool(self):
        ctx = MarketingContext(pool=object(), instagram=None, created_by="admin")
        out = json.loads(await tool_by_name(ctx, "ver_datas_comerciais").ainvoke({}))
        assert out and {"data", "nome", "comecar_campanha_em"} <= out[0].keys()

    async def test_create_draft(self):
        ctx = MarketingContext(pool=object(), instagram=None, created_by="admin")
        when = (datetime.now(TZ) + timedelta(days=3)).strftime("%Y-%m-%dT19:00")
        with patch.object(
            tools_mod.pub_store,
            "create_suggested_draft",
            new=AsyncMock(return_value=42),
        ) as create:
            out = await tool_by_name(ctx, "criar_rascunho_de_post").ainvoke(
                {
                    "tipo": "Reels",
                    "briefing": "Scarpin nude no pé\nandando na rua",
                    "legenda": "Conforto que anda com você. Chama no Direct!",
                    "data_sugerida": when,
                    "justificativa": "Reels têm o maior alcance médio",
                }
            )
        assert json.loads(out)["id"] == 42
        kwargs = create.await_args.kwargs
        assert kwargs["kind"] == "reels"
        assert kwargs["planned_for"].tzinfo is not None
        assert kwargs["created_by"] == "agente-marketing (admin)"
        assert ctx.actions[0]["publication_id"] == 42
        assert ctx.actions[0]["title"] == "Scarpin nude no pé"

    async def test_create_draft_story_drops_caption(self):
        ctx = MarketingContext(pool=object(), instagram=None, created_by="admin")
        when = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%dT10:00")
        with patch.object(
            tools_mod.pub_store, "create_suggested_draft", new=AsyncMock(return_value=1)
        ) as create:
            await tool_by_name(ctx, "criar_rascunho_de_post").ainvoke(
                {
                    "tipo": "story",
                    "briefing": "b",
                    "legenda": "texto",
                    "data_sugerida": when,
                    "justificativa": "j",
                }
            )
        assert create.await_args.kwargs["caption"] == ""

    async def test_create_draft_rejected_tells_model_why(self):
        ctx = MarketingContext(pool=object(), instagram=None, created_by="admin")
        with patch.object(
            tools_mod.pub_store, "create_suggested_draft", new=AsyncMock()
        ) as create:
            out = await tool_by_name(ctx, "criar_rascunho_de_post").ainvoke(
                {
                    "tipo": "feed",
                    "briefing": "b",
                    "legenda": "Por R$ 99",
                    "data_sugerida": "2020-01-01T10:00",
                    "justificativa": "j",
                }
            )
        assert out.startswith("Rascunho NÃO criado")
        create.assert_not_awaited()

    async def test_create_draft_limit_per_turn(self):
        ctx = MarketingContext(pool=object(), instagram=None, created_by="admin")
        ctx.actions = [{"type": "draft"}] * tools_mod.MAX_DRAFTS_PER_TURN
        out = await tool_by_name(ctx, "criar_rascunho_de_post").ainvoke(
            {
                "tipo": "feed",
                "briefing": "b",
                "legenda": "l",
                "data_sugerida": "2099-01-01T10:00",
                "justificativa": "j",
            }
        )
        assert "Limite" in out


# ---------------------------------------------------------------------------
# Montagem do turno
# ---------------------------------------------------------------------------


class TestTurn:
    def test_history_is_bounded(self):
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
            for i in range(40)
        ]
        msgs = build_messages(history, "nova")
        assert len(msgs) == agent_mod.HISTORY_LIMIT + 1
        assert msgs[-1].content == "nova"

    def test_today_line(self):
        line = today_line(datetime(2026, 11, 24, 15, 30, tzinfo=TZ))
        assert line.startswith("terça-feira, 24/11/2026 15:30")
        # Dias da semana vêm prontos do código (o modelo erra essa conta)
        assert "sáb 28/11" in line and "dom 29/11" in line
        assert "ter 08/12" in line and "09/12" not in line
        assert "24/11," not in line.split("\n")[1]

    def test_prompt_has_today_placeholder(self):
        assert "{today}" in agent_mod.SYSTEM_PROMPT

    @pytest.mark.parametrize(
        "reply",
        [
            "Vou criar os rascunhos agora (exceto o já agendado).",
            "Já vou deixar tudo na tela Publicar.",
            "Criarei os 4 posts em seguida.",
            # Afirmações (só checadas quando nada foi criado de fato)
            "### Rascunhos já criados:",
            "Criei 4 rascunhos na tela Publicar.",
            "Deixei tudo na tela Publicar para vocês.",
        ],
    )
    def test_detects_promise_or_claim(self, reply):
        assert agent_mod.promised_drafts(reply)

    @pytest.mark.parametrize(
        "reply",
        [
            "Quer que eu crie os rascunhos?",
            "Posso criar os rascunhos se vocês aprovarem o plano.",
            "Os Reels estão entregando o maior alcance.",
        ],
    )
    def test_ignores_done_or_question(self, reply):
        assert not agent_mod.promised_drafts(reply)


def _fake_agent(*turns):
    """Agente falso: cada ainvoke devolve o próximo conjunto de mensagens."""
    from langchain_core.messages import AIMessage

    calls: list[list] = []
    replies = iter(turns)

    async def ainvoke(state, config=None):
        calls.append(state["messages"])
        reply, on_call = next(replies)
        if on_call:
            on_call()
        return {"messages": [*state["messages"], AIMessage(content=reply)]}

    fake = AsyncMock()
    fake.ainvoke.side_effect = ainvoke
    return fake, calls


class TestSelfCorrection:
    def _ctx(self):
        return MarketingContext(pool=AsyncMock(), instagram=None, created_by="admin")

    def _patches(self, fake):
        return (
            patch.object(agent_mod, "create_agent", return_value=fake),
            patch.object(agent_mod, "create_chat_model"),
            patch.object(agent_mod, "build_tools", return_value=[]),
        )

    async def test_nudges_once_when_promise_is_not_kept(self):
        ctx = self._ctx()

        def create():
            ctx.actions.append({"type": "draft", "publication_id": 1})

        fake, calls = _fake_agent(
            ("Vou criar os rascunhos agora.", None),
            ("Criei 1 rascunho na tela Publicar.", create),
        )
        p1, p2, p3 = self._patches(fake)
        with p1, p2, p3:
            result = await agent_mod.run_turn(ctx, [], "Monte o plano da semana")

        assert len(calls) == 2
        assert calls[1][-1].content == agent_mod.CREATE_NUDGE
        assert result.reply == "Criei 1 rascunho na tela Publicar."

    async def test_no_nudge_when_drafts_were_created(self):
        ctx = self._ctx()

        def create():
            ctx.actions.append({"type": "draft", "publication_id": 1})

        fake, calls = _fake_agent(("Criei e vou criar mais na próxima.", create))
        p1, p2, p3 = self._patches(fake)
        with p1, p2, p3:
            await agent_mod.run_turn(ctx, [], "Plano")
        assert len(calls) == 1

    async def test_empty_final_text_after_drafts_becomes_summary(self):
        ctx = self._ctx()

        def create():
            ctx.actions.append(
                {
                    "type": "draft",
                    "publication_id": 7,
                    "kind": "reels",
                    "planned_for": "2026-11-28T20:00:00-03:00",
                    "title": "Reels Black Friday na loja",
                }
            )

        fake, _ = _fake_agent(("", create))
        p1, p2, p3 = self._patches(fake)
        with p1, p2, p3:
            result = await agent_mod.run_turn(ctx, [], "Plano")
        assert result.reply.startswith("Criei 1 rascunho na tela Publicar")
        assert "sáb 28/11 20:00" in result.reply
        assert "Reels Black Friday na loja" in result.reply

    async def test_nudge_is_bounded_to_one_retry(self):
        ctx = self._ctx()
        fake, calls = _fake_agent(
            ("Vou criar os rascunhos.", None),
            ("Vou criar os rascunhos.", None),
        )
        p1, p2, p3 = self._patches(fake)
        with p1, p2, p3:
            result = await agent_mod.run_turn(ctx, [], "Plano")
        assert len(calls) == 2
        # A equipe não fica achando que algo foi criado
        assert result.reply.endswith(agent_mod.UNKEPT_PROMISE_NOTE)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

ROUTE = "whatsapp_langchain.server.routes.marketing"
client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def route_env():
    from whatsapp_langchain.server.dependencies import require_admin_session

    app.dependency_overrides[require_admin_session] = lambda: "admin"
    store = AsyncMock()
    store.get_thread.return_value = {"id": 1, "title": "Nova conversa"}
    store.list_messages.return_value = []
    store.add_message.side_effect = lambda pool, tid, **kw: {"role": kw["role"], **kw}
    with (
        patch(f"{ROUTE}.get_pool", new=AsyncMock(return_value=AsyncMock())),
        patch(f"{ROUTE}.store", store),
        patch(f"{ROUTE}._rename", new=AsyncMock()),
    ):
        yield store
    app.dependency_overrides.clear()


class TestRoutes:
    def test_ask_saves_both_messages_with_actions(self, route_env):
        async def fake_turn(ctx, history, question):
            ctx.actions.append({"type": "draft", "publication_id": 7})
            return agent_mod.TurnResult(
                reply="Plano pronto", tools_used=["ver_datas_comerciais"]
            )

        with patch(f"{ROUTE}.run_turn", new=fake_turn):
            r = client.post(
                "/api/marketing/threads/1/messages", json={"content": "Plano?"}
            )
        assert r.status_code == 200
        user, reply = r.json()["messages"]
        assert user["content"] == "Plano?"
        assert reply["content"] == "Plano pronto"
        types = [a["type"] for a in reply["actions"]]
        assert types == ["draft", "tools"]

    def test_failure_is_friendly_and_flagged(self, route_env):
        with patch(
            f"{ROUTE}.run_turn",
            new=AsyncMock(side_effect=RuntimeError("401 User not found")),
        ):
            r = client.post("/api/marketing/threads/1/messages", json={"content": "Oi"})
        reply = r.json()["messages"][1]
        assert "OpenRouter" in reply["content"]
        assert {"type": "error"} in reply["actions"]

    def test_error_replies_are_not_sent_to_model(self, route_env):
        route_env.list_messages.return_value = [
            {"role": "user", "content": "a", "actions": []},
            {"role": "assistant", "content": "erro", "actions": [{"type": "error"}]},
        ]
        seen = {}

        async def fake_turn(ctx, history, question):
            seen["history"] = history
            return agent_mod.TurnResult(reply="ok", tools_used=[])

        with patch(f"{ROUTE}.run_turn", new=fake_turn):
            client.post("/api/marketing/threads/1/messages", json={"content": "b"})
        assert [m["content"] for m in seen["history"]] == ["a"]

    def test_busy_thread_conflict(self, route_env):
        from whatsapp_langchain.server.routes import marketing

        lock = marketing._lock(1)
        import asyncio

        asyncio.run(lock.acquire())
        try:
            r = client.post("/api/marketing/threads/1/messages", json={"content": "x"})
            assert r.status_code == 409
        finally:
            lock.release()

    def test_unknown_thread(self, route_env):
        route_env.get_thread.return_value = None
        r = client.post("/api/marketing/threads/9/messages", json={"content": "x"})
        assert r.status_code == 404


class TestNotExposedToCustomers:
    def test_marketing_agent_not_in_webhook_catalog(self):
        from whatsapp_langchain.agents.loader import list_agents

        assert not any("marketing" in a for a in list_agents())
