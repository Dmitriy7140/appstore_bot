from aiogram.types import CallbackQuery

from aiogram import Router
from config.config_messages import AMOUNTS

from keyboards.amounts_buttons import amounts_keyboard
from services.sender_service import lazy_send_photo

rt = Router()
@rt.callback_query(lambda c: c.data.split(":")[0] in AMOUNTS)
async def service_menu(callback: CallbackQuery):
    keyboard = amounts_keyboard(callback.data)

    await lazy_send_photo(callback, callback.data, keyboard)
    await callback.answer()