import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from menus.start import start


class StartRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_start_registers_user_before_showing_menu(self) -> None:
        events: list[str] = []
        state = AsyncMock()
        state.clear.side_effect = lambda: events.append("state")

        async def register_user(telegram_id: int, username: str | None) -> None:
            self.assertEqual((telegram_id, username), (12931239, "Two_Pay_User"))
            events.append("registration")

        async def show_menu(message) -> None:
            events.append("menu")

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=12931239, username="Two_Pay_User")
        )
        command = SimpleNamespace(args=None)
        with (
            patch("menus.start.register_bot_user", register_user),
            patch("menus.start.show_main_menu", show_menu),
        ):
            await start(message, command, state)

        self.assertEqual(events, ["state", "registration", "menu"])


if __name__ == "__main__":
    unittest.main()
