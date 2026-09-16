import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from commands.code_inventory import router, show_code_inventory
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
                nominals=(CodeNominalStock(100, 7),),
            ),
            CodeRegionStock(
                region="us",
                available=1,
                nominals=(CodeNominalStock(10, 1),),
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
        self.assertIn("• 100₺: <b>7</b>", text)
        self.assertNotIn("/20", text)
        self.assertIn("складскую админку", text)
        self.assertEqual(message.answer.await_args.kwargs["parse_mode"], "HTML")

    async def test_codes_reports_warehouse_failure(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())
        with patch("commands.code_inventory.get_code_inventory",
                   AsyncMock(side_effect=TwoPayApiError("API unavailable"))):
            await show_code_inventory(message)
        self.assertIn("Не удалось получить остатки со склада", message.answer.await_args.args[0])

    def test_only_codes_command_is_registered(self) -> None:
        from aiogram.filters import Command
        commands = [command for handler in router.message.handlers
                    for filter_ in handler.filters if isinstance(filter_.callback, Command)
                    for command in filter_.callback.commands]
        self.assertEqual(commands, ["codes"])


if __name__ == "__main__":
    unittest.main()
