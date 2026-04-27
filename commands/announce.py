from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from repository.database.database import get_user_ids
from services.notification_service import Mailer

from config.utils import IsAdmin
from config.config_env import ADMIN_IDS, TEST_MODE

router = Router()


# ================= FSM =================

class AnnounceState(StatesGroup):
    waiting_message = State()
    confirm = State()


# ================= Клавиатура =================

def confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data="announce_yes")
    builder.button(text="❌ Нет", callback_data="announce_no")
    builder.adjust(2)
    return builder.as_markup()


# ================= /announce =================

@router.message(Command("announce"), IsAdmin())
async def announce_start(message: Message, state: FSMContext):
    await message.answer("Отправь сообщение для рассылки")
    await state.set_state(AnnounceState.waiting_message)


# ================= Получаем сообщение =================

@router.message(AnnounceState.waiting_message)
async def announce_get_message(message: Message, state: FSMContext):
    await state.update_data(msg=message)

    await message.answer(
        "Отправить это сообщение всем пользователям?",
        reply_markup=confirm_keyboard()
    )

    await state.set_state(AnnounceState.confirm)


# ================= Подтверждение =================

@router.callback_query(AnnounceState.confirm, F.data == "announce_no", IsAdmin())
async def announce_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена")
    await callback.answer()


@router.callback_query(AnnounceState.confirm, F.data == "announce_yes", IsAdmin())
async def announce_confirm(callback: CallbackQuery, state: FSMContext, mailer: Mailer):
    await callback.answer()

    data = await state.get_data()
    msg: Message = data["msg"]



    users = await get_user_ids()

    if not users:
        await callback.message.edit_text("Нет пользователей для рассылки")
        await state.clear()
        return

    await callback.message.edit_text("🚀 Начинаю рассылку...")

    success, failed = await mailer.send_to_many(users if not TEST_MODE else ADMIN_IDS, msg)

    total = users.qsize()

    await callback.message.edit_text(
        f"✅ Рассылка завершена\n\n"
        f"Всего: {total}\n"
        f"Отправлено: {success}\n"
        f"Ошибки: {failed}"
    )

    await state.clear()