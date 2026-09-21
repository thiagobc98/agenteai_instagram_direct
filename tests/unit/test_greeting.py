"""Testes do middleware de saudação (bom dia/tarde/noite + apresentação)."""

from datetime import datetime

import pytest

from whatsapp_langchain.agents.catalog.secretaria.agent import GREETING_INTRO
from whatsapp_langchain.agents.middleware.greeting import (
    _greeting_word,
    build_greeting_prompt,
)

BASE = "PROMPT-BASE"
INTRO = "Aqui quem fala é a Juliana, atendente virtual da Patricia Berberich"


def at(hour: int) -> datetime:
    return datetime(2026, 9, 21, hour, 30)


class TestGreetingWord:
    @pytest.mark.parametrize(
        ("hour", "word"),
        [
            (0, "Bom dia"),
            (11, "Bom dia"),
            (12, "Boa tarde"),
            (17, "Boa tarde"),
            (18, "Boa noite"),
            (23, "Boa noite"),
        ],
    )
    def test_word_by_hour(self, hour, word):
        assert _greeting_word(hour) == word


class TestBuildGreetingPrompt:
    def test_first_turn_introduces_the_agent(self):
        prompt = build_greeting_prompt(BASE, INTRO, at(15), is_first_turn=True)

        assert prompt.startswith(BASE)
        assert f'"Boa tarde! {INTRO}, seja bem-vinda.' in prompt
        assert "15:30" in prompt

    def test_first_turn_has_no_clinic_leftovers(self):
        prompt = build_greeting_prompt(BASE, GREETING_INTRO, at(9), is_first_turn=True)

        for word in ("Luana", "Dra.", "paciente", "consulta", "secretária"):
            assert word not in prompt
        assert "Patricia Berberich" in prompt

    def test_later_turn_does_not_repeat_the_introduction(self):
        prompt = build_greeting_prompt(BASE, INTRO, at(20), is_first_turn=False)

        assert INTRO not in prompt
        assert '"Boa noite!"' in prompt
        assert "sem repetir a apresentação" in prompt
