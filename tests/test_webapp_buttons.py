import unittest

from keyboards.menu_buttons import main_menu_keyboard
from keyboards.webapp_buttons import mini_app_url, payment_moved_keyboard


class WebAppButtonsTests(unittest.TestCase):
    def test_all_mini_app_buttons_use_testamos(self) -> None:
        self.assertEqual(
            mini_app_url("appstore"),
            "https://testamos.2pay.money?s=appstore",
        )

        main_urls = [
            button.web_app.url
            for row in main_menu_keyboard().inline_keyboard
            for button in row
            if button.web_app is not None
        ]
        moved_urls = [
            button.web_app.url
            for row in payment_moved_keyboard("ps").inline_keyboard
            for button in row
            if button.web_app is not None
        ]
        self.assertEqual(
            main_urls,
            [
                "https://testamos.2pay.money?s=appstore",
                "https://testamos.2pay.money?s=ps",
            ],
        )
        self.assertEqual(
            moved_urls,
            ["https://testamos.2pay.money?s=ps"],
        )


if __name__ == "__main__":
    unittest.main()
