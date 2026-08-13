from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from keyboards.webapp_buttons import mini_app_url


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛒 App Store",
                    web_app=WebAppInfo(url=mini_app_url("appstore")),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 PlayStation",
                    web_app=WebAppInfo(url=mini_app_url("ps")),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🇹🇷 Сменить регион и забрать бонус 10 лир",
                    url="https://t.me/MANAGER_2PAY",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐️ Отзывы и гарантии",
                    callback_data="reviews_menu",
                )
            ],
        ]
    )
