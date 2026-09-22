"""Testes da tool save_customer_whatsapp (agents/tools/handoff.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from whatsapp_langchain.agents.tools.handoff import save_customer_whatsapp

save_customer_whatsapp_fn = save_customer_whatsapp.coroutine
MODULE = "whatsapp_langchain.agents.tools.handoff"


def _make_runtime(*, user_id: str | None = "17841400000000001"):
    configurable = {"thread_id": "thread-test"}
    if user_id:
        configurable["user_id"] = user_id
    runtime = MagicMock()
    runtime.config = {"configurable": configurable}
    return runtime


class TestToolMetadata:
    def test_tool_has_correct_name(self):
        assert save_customer_whatsapp.name == "save_customer_whatsapp"

    def test_tool_has_whatsapp_parameter(self):
        schema = save_customer_whatsapp.get_input_schema()
        assert "whatsapp" in schema.model_fields


class TestSaveCustomerWhatsapp:
    def test_normalizes_and_saves_a_valid_number(self):
        pool = object()
        with (
            patch(f"{MODULE}.get_pool", new=AsyncMock(return_value=pool)),
            patch(f"{MODULE}.set_customer_whatsapp", new_callable=AsyncMock) as save,
        ):
            result = asyncio.run(
                save_customer_whatsapp_fn("(31) 99999-8888", runtime=_make_runtime())
            )

        assert "salvo" in result.lower()
        save.assert_awaited_once_with(
            pool, "17841400000000001", whatsapp="5531999998888"
        )

    def test_rejects_an_invalid_number_without_saving(self):
        with patch(f"{MODULE}.set_customer_whatsapp", new_callable=AsyncMock) as save:
            result = asyncio.run(
                save_customer_whatsapp_fn("abc", runtime=_make_runtime())
            )

        assert "não parece um whatsapp válido" in result.lower()
        save.assert_not_awaited()

    def test_missing_user_id_returns_error_without_saving(self):
        with patch(f"{MODULE}.set_customer_whatsapp", new_callable=AsyncMock) as save:
            result = asyncio.run(
                save_customer_whatsapp_fn(
                    "31999998888", runtime=_make_runtime(user_id=None)
                )
            )

        assert "user_id" in result.lower()
        save.assert_not_awaited()
