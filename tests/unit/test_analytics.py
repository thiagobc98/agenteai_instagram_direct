"""Testes das regras de métricas do dashboard (sem banco)."""

import re
from datetime import date

import pytest

from whatsapp_langchain.shared.analytics import (
    TOPICS,
    _handoff_sql,
    fill_daily,
    handoff_digits,
)


class TestHandoffDigits:
    @pytest.mark.parametrize(
        ("phone", "digits"),
        [
            ("31993456562", "31993456562"),
            ("(31) 99345-6562", "31993456562"),
            ("+55 31 99345-6562", "5531993456562"),
            ("", ""),
        ],
    )
    def test_keeps_only_digits(self, phone, digits):
        assert handoff_digits(phone) == digits


class TestHandoffSql:
    def test_disabled_without_phone(self):
        assert _handoff_sql(False) == "FALSE"

    def test_compares_only_digits_of_done_responses(self):
        sql = _handoff_sql(True)
        assert "status = 'done'" in sql
        assert "regexp_replace" in sql and "LIKE %(hl)s" in sql

    def test_prefix_is_applied_to_columns(self):
        sql = _handoff_sql(True, "m.")
        assert "m.status" in sql and "m.response" in sql


class TestFillDaily:
    DAYS = [date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21)]

    def test_days_without_messages_are_zero(self):
        series = fill_daily(self.DAYS, {}, {})

        assert [d["date"] for d in series] == ["2026-09-19", "2026-09-20", "2026-09-21"]
        assert all(d["messages"] == 0 and d["new_leads"] == 0 for d in series)

    def test_merges_messages_and_leads_by_day(self):
        series = fill_daily(
            self.DAYS,
            {date(2026, 9, 20): (10, 4, 3, 2)},
            {date(2026, 9, 20): 2, date(2026, 9, 21): 1},
        )

        assert series[1] == {
            "date": "2026-09-20",
            "messages": 10,
            "contacts": 4,
            "new_leads": 2,
            "handoffs": 3,
            "handoff_contacts": 2,
        }
        assert series[2]["new_leads"] == 1 and series[2]["messages"] == 0


def _matches(topic_key: str, text: str) -> bool:
    """Aproxima a regex POSIX do Postgres: as bordas \\m e \\M viram \\b."""
    regex = next(r for k, _, r in TOPICS if k == topic_key)
    pattern = regex.replace("\\m", "\\b").replace("\\M", "\\b")
    return re.search(pattern, text, re.IGNORECASE) is not None


class TestTopics:
    @pytest.mark.parametrize(
        ("topic", "text"),
        [
            ("preco", "Quanto custa esse scarpin?"),
            ("preco", "qual o valor?"),
            ("tamanho", "tem no 37?"),
            ("tamanho", "qual a numeração de vocês"),
            ("estoque", "tem em estoque na cor preta?"),
            ("frete", "fazem entrega pra Recife? qual o prazo"),
            ("pagamento", "aceita pix ou parcela no cartão?"),
            ("troca", "como faço a troca se não servir"),
            ("loja", "qual o horário da loja?"),
            ("loja", "onde fica a loja"),
            ("modelos", "queria ver as sandálias novas"),
        ],
    )
    def test_matches_typical_questions(self, topic, text):
        assert _matches(topic, text)

    def test_unrelated_message_matches_no_topic(self):
        assert not any(_matches(key, "Oi, bom dia!") for key, _, _ in TOPICS)

    def test_size_does_not_match_inside_other_numbers(self):
        assert not _matches("tamanho", "meu cep é 30350370")

    def test_keys_are_unique(self):
        keys = [k for k, _, _ in TOPICS]
        assert len(keys) == len(set(keys))
