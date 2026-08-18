from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


WEB_APP_URL = "https://2pay-tma.vercel.app"


def mini_app_url(start_param: str) -> str:
    """Return the Mini App URL pre-opened on the requested storefront section."""
    parts = urlsplit(WEB_APP_URL)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["startapp"] = start_param
    return urlunsplit((*parts[:3], urlencode(query), parts.fragment))


def payment_moved_keyboard(service: str) -> InlineKeyboardMarkup:
    """Offer the Mini App instead of creating a legacy bot payment."""
    section = "ps" if service.lower() == "ps" else "appstore"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛒 Открыть веб-приложение",
                    web_app=WebAppInfo(url=mini_app_url(section)),
                )
            ],
            [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")],
        ]
    )
