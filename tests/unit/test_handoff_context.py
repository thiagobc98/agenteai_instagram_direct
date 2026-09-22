"""Testes de build_handoff_section (agents/middleware/handoff_context.py)."""

from whatsapp_langchain.agents.middleware.handoff_context import (
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
