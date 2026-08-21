from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from config.utils import IsAdmin
from services.two_pay_api_client import get_audience

rt = Router()


@rt.message(Command("allusers"), IsAdmin())
async def all_users(message: Message):
    paid = await get_audience("paid")
    never_paid = await get_audience("never_paid")
    all_users_list = await get_audience("all")

    text = (
        f"👥 <b>Пользователи бота</b>\n\n"
        f"💳 Оплатили: {len(paid)}\n"
        f"⚠️ Не оплатили: {len(never_paid)}\n"
        f"📊 Всего пользователей: {len(all_users_list)}"
    )

    await message.answer(text, parse_mode="HTML")
