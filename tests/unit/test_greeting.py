"""Testes do middleware de saudação (bom dia/tarde/noite + apresentação)."""

from datetime import datetime

import pytest

from whatsapp_langchain.agents.catalog.secretaria.agent import GREETING_INTRO
from whatsapp_langchain.agents.middleware.greeting import (
    _greeting_word,
    build_greeting_prompt,
    is_greeting_only,
)

BASE = "PROMPT-BASE"
INTRO = "Aqui quem fala é a Juliana, atendente virtual da Patricia Berberich"


def at(hour: int) -> datetime:
    return datetime(2026, 9, 21, hour, 30)


def prompt(hour: int, *, first: bool, last: str = "") -> str:
    return build_greeting_prompt(
        BASE, INTRO, at(hour), is_first_turn=first, last_message=last
    )


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


class TestIsGreetingOnly:
    @pytest.mark.parametrize(
        "text",
        [
            "Oi",
            "oii",
            "Oiii!!",
            "Olá",
            "ola, tudo bem?",
            "Bom dia!",
            "boa tarde 😊",
            "Boa noite, tudo bom?",
            "oi gente",
            "E aí",
            "Oi\nTudo bem?",
            "oi, td bem?",
        ],
    )
    def test_plain_greetings(self, text):
        assert is_greeting_only(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Oi, quanto custa?",
            "Quem tá falando?",
            "Bom dia, tem o 37?",
            "Quero ver as sandálias",
            "tudo bem, e o valor?",
            "Amanhã abre que horas",
            "",
            "😊",
        ],
    )
    def test_greeting_with_question_or_other_text_is_not_greeting_only(self, text):
        assert not is_greeting_only(text)


class TestFirstTurn:
    def test_introduces_the_agent(self):
        text = prompt(15, first=True, last="Oi")

        assert text.startswith(BASE)
        assert f'"Boa tarde! {INTRO}, seja bem-vinda.' in text
        assert "15:30" in text

    def test_has_no_clinic_leftovers(self):
        text = build_greeting_prompt(
            BASE, GREETING_INTRO, at(9), is_first_turn=True, last_message="Oi"
        )

        for word in ("Luana", "Dra.", "paciente", "consulta", "secretária"):
            assert word not in text
        assert "Patricia Berberich" in text


class TestReturningCustomer:
    def test_greeting_only_gets_welcome_back_not_just_the_greeting(self):
        text = prompt(15, first=False, last="Oi")

        assert "JÁ conversou com você antes" in text
        assert "NUNCA responda apenas com a saudação" in text
        assert (
            '"Boa tarde! Que bom falar com você de novo, seja bem-vinda novamente'
            in text
        )
        assert "Como posso te ajudar hoje?" in text

    def test_welcome_back_uses_the_greeting_of_the_hour(self):
        assert '"Bom dia! Que bom falar' in prompt(9, first=False, last="oi")
        assert '"Boa noite! Que bom falar' in prompt(21, first=False, last="oi")

    def test_returning_does_not_repeat_the_full_introduction(self):
        for last in ("Oi", "Quero ver as sandálias"):
            assert INTRO not in prompt(20, first=False, last=last)

    def test_returning_with_a_request_answers_it_directly(self):
        text = prompt(15, first=False, last="Boa tarde, tem o 37?")

        assert "Responda direto ao que ela pediu" in text
        assert "Que bom falar com você de novo" not in text
        assert '"Boa tarde!"' in text

    def test_returning_has_no_clinic_leftovers(self):
        text = prompt(15, first=False, last="Oi")

        for word in ("Luana", "Dra.", "paciente", "consulta", "secretária"):
            assert word not in text
