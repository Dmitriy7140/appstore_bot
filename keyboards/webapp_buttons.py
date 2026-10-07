import os

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


WEB_APP_URL = os.environ.get("TMA_WEB_APP_URL", "https://testamos.2pay.money").strip()


def mini_app_url(section: str) -> str:
    """Return the Mini App URL pre-opened on the requested storefront section."""
    # URLs/landing slugs belong to the storefront deployment, not bot code.
    configured = os.environ.get(f"TMA_{section.upper()}_URL", WEB_APP_URL).strip()
    parts = urlsplit(configured)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Mini App URL must be an HTTPS storefront URL")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    # This is a WebApp URL, not a t.me Mini App deep-link. The frontend reads
    # `s` from location.search; Telegram only puts `startapp` into initData when
    # it appears on a t.me/<bot>?startapp=... link.
    query["s"] = section
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
