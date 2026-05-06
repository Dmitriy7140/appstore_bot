from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from config.utils import IsAdmin
from repository.database.database import get_user_ids_by_state

rt = Router()


@rt.message(Command("allusers"), IsAdmin())
async def all_users(message: Message):
    rfool = await get_user_ids_by_state("rfool")
    paid = await get_user_ids_by_state("paid")
    others = await get_user_ids_by_state("others")
    all_users_list = await get_user_ids_by_state("all")

    text = (
        f"👥 <b>Пользователи бота</b>\n\n"
        f"🚧 Застряли на регионе: {len(rfool)}\n"
        f"💳 Оплатили: {len(paid)}\n"
        f"⚠️ Не оплатили / не в регионе: {len(others)}\n"
        f"📊 Всего пользователей: {len(all_users_list)}"
    )

    await message.answer(text, parse_mode="HTML")