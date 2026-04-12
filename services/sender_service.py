from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from config.config_messages import SERVICES, AMOUNTS


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