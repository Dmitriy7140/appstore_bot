from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


WEB_APP_URL = "https://public-inky-sigma.vercel.app"


def _mini_app_url(start_param: str) -> str:
    """Добавляет выбранный раздел к URL Telegram Mini App."""
    parts = urlsplit(WEB_APP_URL)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["startapp"] = start_param
    return urlunsplit((*parts[:3], urlencode(query), parts.fragment))


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛒 App Store",
                    web_app=WebAppInfo(url=_mini_app_url("appstore")),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎮 PlayStation",
                    web_app=WebAppInfo(url=_mini_app_url("ps")),
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
                    url="https://t.me/review_2pay",
                )
            ],
        ]
    )
