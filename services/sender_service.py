from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup

from config.config_messages import SERVICES, AMOUNTS
from config.config_env import ADMIN_CHAT_ID, TEST_MODE

from repository.database.database import add_transaction
from services.media_cache import send_cached_photo






async def lazy_send_photo(callback, service: str, keyboard:InlineKeyboardMarkup):

    if callback.data.endswith("topup"):
        service, _ = service.split(":")

        data = AMOUNTS[service]
        folder = "static/amounts"
    else:
        data = SERVICES[service]
        folder = "static/menus"

    # file_id-кэш (postgres) сам решает: слать строкой или залить файл один раз
    await send_cached_photo(
        callback.message,
        f"{folder}/{service}.png",
        caption=data["text"],
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

async def send_transaction_notice(bot, telegram_id:int, tx_id:str, amount:int, code:str):
    await add_transaction(bot, telegram_id, tx_id, amount)

    # 2. отправляем уведомление админу
    user_link = f"tg://user?id={telegram_id}"

    text = (
        f"💰 Новая {"тестовая " if TEST_MODE else ""}транзакция!\n\n"
        f"👤 <a href='{user_link}'>Пользователь: {telegram_id}</a>\n\n"
        f"🆔 ID Транзакции: <tg-spoiler>{tx_id}</tg-spoiler>\n\n"
        f"🔑 Код: <tg-spoiler> {"тест" if TEST_MODE else code} </tg-spoiler>\n\n"
        f"💵 Сумма: {amount} RUB"
    )

    await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="html")

