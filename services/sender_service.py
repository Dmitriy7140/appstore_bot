from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup

from config.config_messages import SERVICES, AMOUNTS
from services.media_cache import send_cached_photo






async def lazy_send_photo(callback, service: str, keyboard:InlineKeyboardMarkup):

    if callback.data.endswith("topup"):
        service, _ = service.split(":")

        data = AMOUNTS[service]
        folder = "static/amounts"
    else:
        data = SERVICES[service]
        folder = "static/menus"

    # file_id-кэш в памяти сам решает: слать строкой или залить файл один раз
    await send_cached_photo(
        callback.message,
        f"{folder}/{service}.png",
        caption=data["text"],
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

