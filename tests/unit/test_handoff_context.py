"""Testes de agents/middleware/handoff_context.py (encaminhamento à Patrícia)."""

import pytest

from whatsapp_langchain.agents.middleware.handoff_context import (
    MAX_WHATSAPP_ASKS,
    PATRICIA_FULL_LINK,
    PATRICIA_LINK,
    build_handoff_section,
    expand_patricia_link,
    whatsapp_link,
)


class TestWhatsappLink:
    @pytest.mark.parametrize(
        "phone",
        ["31993456562", "(31) 99345-6562", "+55 31 99345-6562", "5531993456562"],
    )
    def test_any_format_becomes_wa_me_with_country_code(self, phone):
        assert whatsapp_link(phone, text="") == "https://wa.me/5531993456562"

    def test_prefilled_text_is_url_encoded(self):
        link = whatsapp_link("31993456562", text="Oi, Patrícia!")
        assert link == "https://wa.me/5531993456562?text=Oi%2C%20Patr%C3%ADcia%21"

    def test_configured_links(self):
        assert PATRICIA_LINK == "https://wa.me/5531993456562"
        assert PATRICIA_FULL_LINK.startswith(PATRICIA_LINK + "?text=")


class TestExpandPatriciaLink:
    @pytest.mark.parametrize(
        "written",
        [
            "https://wa.me/5531993456562",
            "wa.me/5531993456562",
            "http://wa.me/5531993456562?text=Oi",
            "https://api.wa.me/5531993456562/",
        ],
    )
    def test_short_or_broken_variants_become_the_full_link(self, written):
        text = f"Pode chamar ela direto:\n{written}"
        assert (
            expand_patricia_link(text)
            == f"Pode chamar ela direto:\n{PATRICIA_FULL_LINK}"
        )

    def test_keeps_trailing_punctuation_and_other_links(self):
        text = "Chama: https://wa.me/5531993456562. Ou https://wa.me/5511999999999"
        out = expand_patricia_link(text)
        assert f"{PATRICIA_FULL_LINK}." in out
        assert "https://wa.me/5511999999999" in out

    def test_is_idempotent(self):
        once = expand_patricia_link(PATRICIA_LINK)
        assert expand_patricia_link(once) == once

    def test_text_without_link_is_unchanged(self):
        assert expand_patricia_link("Oi! Tudo bem?") == "Oi! Tudo bem?"
        assert expand_patricia_link("") == ""


class TestBuildHandoffSection:
    def test_without_whatsapp_asks_and_sends_link_in_the_same_message(self):
        text = build_handoff_section(None)

        assert "NÃO tem" in text
        assert "MESMA mensagem" in text
        assert "peça o WhatsApp" in text
        assert "save_customer_whatsapp" in text
        assert PATRICIA_LINK in text

    def test_with_whatsapp_does_not_ask_again_but_sends_link(self):
        text = build_handoff_section("5531999998888")

        assert "JÁ TEM" in text
        assert "Não peça de novo" in text
        assert PATRICIA_LINK in text

    def test_empty_string_is_treated_as_unknown(self):
        assert build_handoff_section("") == build_handoff_section(None)

    def test_below_max_asks_still_tells_the_agent_to_ask(self):
        text = build_handoff_section(None, ask_count=MAX_WHATSAPP_ASKS - 1)

        assert "peça o WhatsApp" in text
        assert "desista" not in text.lower()

    def test_at_max_asks_stops_asking_and_only_sends_link(self):
        text = build_handoff_section(None, ask_count=MAX_WHATSAPP_ASKS)

        assert "NÃO peça de novo" in text
        assert "desista" in text.lower()
        assert PATRICIA_LINK in text
        assert "save_customer_whatsapp" in text

    def test_known_whatsapp_ignores_ask_count(self):
        text = build_handoff_section("5531999998888", ask_count=MAX_WHATSAPP_ASKS)

        assert "JÁ TEM" in text
        assert "desista" not in text.lower()

    def test_section_never_carries_the_long_link(self):
        # O modelo copia o link curto; o longo é colocado pelo código
        assert PATRICIA_FULL_LINK not in build_handoff_section(None)
