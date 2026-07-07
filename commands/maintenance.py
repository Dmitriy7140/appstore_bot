from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config.utils import IsAdmin
from services.maintenance import set_broke, is_broke

router = Router()


@router.message(Command("broke"), IsAdmin())
async def toggle_broke(message: Message):
    """Тумблер режима поломки. Только админ."""
    new_state = not is_broke()
    await set_broke(new_state)
    if new_state:
        await message.answer(
            "🔧 Режим поломки ВКЛЮЧЁН.\n"
            "Любое нажатие кнопки теперь ведёт на менеджера.\n\n"
            "Выключить — снова /broke"
        )
    else:
        await message.answer("✅ Режим поломки ВЫКЛЮЧЕН. Бот работает штатно.")
