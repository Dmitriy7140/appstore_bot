from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from config.config_messages import SERVICES, AMOUNTS
from config.config_env import ADMIN_CHAT_ID
from repository.database.database import add_transaction





async def lazy_send_photo(callback, service: str, keyboard:InlineKeyboardMarkup):

    if callback.data.endswith("topup"):
        service, _ = service.split(":")

        data = AMOUNTS[service]
        folder= "static/amounts"
    else:
        data = SERVICES[service]
        folder = "static/menus"


    if data["file_id"]:
        await callback.message.answer_photo(
            photo=data["file_id"],
            caption=data["text"],
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        return


    photo = FSInputFile(f"{folder}/{service}.png")

    msg = await callback.message.answer_photo(
        photo=photo,
        caption=data["text"],
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


    file_id = msg.photo[-1].file_id

    if callback.data.endswith("topup"):
        AMOUNTS[service]["file_id"] = file_id
    else:
        SERVICES[service]["file_id"] = file_id

async def send_transaction_notice(bot, telegram_id:int, tx_id:str, amount:int, code:str):
    await add_transaction(telegram_id, tx_id, amount)

    # 2. отправляем уведомление админу
    user_link = f"tg://user?id={telegram_id}"

    text = (
        f"💰 Новая транзакция\n\n"
        f"👤 <a href='{user_link}'>Пользователь:{telegram_id}</a>\n\n"
        f"🆔 ID Транзакции:<tg-spoiler>{tx_id}</tg-spoiler>\n\n"
        f"🔑 Код:<tg-spoiler> {code} </tg-spoiler>\n\n"
        f"💵 Сумма: {amount} RUB"
    )

    await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="html")