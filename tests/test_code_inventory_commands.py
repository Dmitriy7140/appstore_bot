import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from commands.code_inventory import refresh_codes, show_code_inventory
from services.two_pay_api_client import (
    CodeInventoryStock,
    CodeNominalStock,
    CodeRegionStock,
    TwoPayApiError,
)


def inventory() -> CodeInventoryStock:
    return CodeInventoryStock(
        total_available=8,
        regions=(
            CodeRegionStock(
                region="tr",
                available=7,
                nominals=(CodeNominalStock(100, 7, 20),),
            ),
            CodeRegionStock(
                region="us",
                available=1,
                nominals=(CodeNominalStock(10, 1, 2),),
            ),
        ),
    )


class CodeInventoryCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_codes_formats_api_inventory(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        with patch(
            "commands.code_inventory.get_code_inventory",
            AsyncMock(return_value=inventory()),
        ):
            await show_code_inventory(message)

        text = message.answer.await_args.args[0]
        self.assertIn("Всего доступно: <b>8</b>", text)
        self.assertIn("🇹🇷 Турция: <b>7</b>", text)
        self.assertIn("• 100₺: <b>7</b>/20", text)
        self.assertEqual(message.answer.await_args.kwargs["parse_mode"], "HTML")

    async def test_refreshcodes_edits_progress_message_with_new_inventory(self) -> None:
        progress = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(answer=AsyncMock(return_value=progress))
        with patch(
            "commands.code_inventory.refresh_code_inventory",
            AsyncMock(return_value=inventory()),
        ):
            await refresh_codes(message)

        self.assertIn("Кэш кодов обновлён", progress.edit_text.await_args.args[0])
        self.assertEqual(progress.edit_text.await_args.kwargs["parse_mode"], "HTML")

    async def test_refreshcodes_reports_api_failure(self) -> None:
        progress = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(answer=AsyncMock(return_value=progress))
        with patch(
            "commands.code_inventory.refresh_code_inventory",
            AsyncMock(side_effect=TwoPayApiError("API unavailable")),
        ):
            await refresh_codes(message)

        self.assertIn("Не удалось полностью обновить", progress.edit_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
