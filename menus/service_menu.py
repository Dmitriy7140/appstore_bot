from aiogram.types import CallbackQuery

from aiogram import Router
from config.config_messages import SERVICES

from keyboards.service_buttons import service_keyboard
from services.sender_service import lazy_send_photo

rt = Router()
@rt.callback_query(lambda c: c.data in SERVICES)
async def service_menu(callback: CallbackQuery):
    keyboard = service_keyboard(callback.data)

    await lazy_send_photo(callback, callback.data, keyboard)
    await callback.answer()