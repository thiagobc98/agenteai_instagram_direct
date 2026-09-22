"""Testes de build_handoff_section (agents/middleware/handoff_context.py)."""

from whatsapp_langchain.agents.middleware.handoff_context import (
    MAX_WHATSAPP_ASKS,
    PATRICIA_CONTACT,
    build_handoff_section,
)


class TestBuildHandoffSection:
    def test_without_whatsapp_tells_the_agent_to_ask_first(self):
        text = build_handoff_section(None)

        assert "NÃO" in text
        assert "peça o WhatsApp" in text
        assert "save_customer_whatsapp" in text
        assert PATRICIA_CONTACT in text

    def test_with_whatsapp_tells_the_agent_it_can_hand_off_directly(self):
        text = build_handoff_section("5531999998888")

        assert "JÁ TEM" in text
        assert "Não peça de novo" in text
        assert PATRICIA_CONTACT in text

    def test_empty_string_is_treated_as_unknown(self):
        assert build_handoff_section("") == build_handoff_section(None)

    def test_below_max_asks_still_tells_the_agent_to_ask(self):
        text = build_handoff_section(None, ask_count=MAX_WHATSAPP_ASKS - 1)

        assert "peça o WhatsApp" in text
        assert "desista" not in text.lower()

    def test_at_max_asks_tells_the_agent_to_give_up_and_hand_off_anyway(self):
        text = build_handoff_section(None, ask_count=MAX_WHATSAPP_ASKS)

        assert "NÃO peça de novo" in text
        assert "desista" in text.lower()
        assert PATRICIA_CONTACT in text
        assert "save_customer_whatsapp" in text

    def test_known_whatsapp_ignores_ask_count(self):
        text = build_handoff_section("5531999998888", ask_count=MAX_WHATSAPP_ASKS)

        assert "JÁ TEM" in text
        assert "desista" not in text.lower()
