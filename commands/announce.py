from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.config_env import TEST_MODE, ADMIN_IDS
from repository.database.database import get_user_ids_by_state
from services.notification_service import Mailer

from config.utils import IsAdmin


router = Router()


# ================= FSM =================

class AnnounceState(StatesGroup):
    waiting_message = State()
    waiting_audience = State()
    confirm = State()


# ================= Клавиатура =================

def confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data="announce_yes")
    builder.button(text="❌ Нет", callback_data="announce_no")
    builder.adjust(2)
    return builder.as_markup()
def audience_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(text="👥 Все", callback_data="announce_all")
    builder.button(text="💸 Оплатили", callback_data="announce_paid")
    builder.button(text="🌍 Застряли в регионе", callback_data="announce_rfool")
    builder.button(text="🤪Не платили и не застряли", callback_data="announce_others")

    builder.adjust(1)
    return builder.as_markup()
# ================= /announce =================

@router.message(Command("announce"), IsAdmin())
async def announce_start(message: Message, state: FSMContext):
    await message.answer("Отправь сообщение для рассылки")
    await state.set_state(AnnounceState.waiting_message)

#========= выбор группы ===============
@router.message(AnnounceState.waiting_message)
async def announce_get_message(message: Message, state: FSMContext):
    await state.update_data(msg=message)

    await message.answer(
        "Кому отправить?",
        reply_markup=audience_keyboard()
    )

    await state.set_state(AnnounceState.waiting_audience)
# ================= Выбираем аудиторию =================
@router.callback_query(AnnounceState.waiting_audience, IsAdmin())
async def announce_get_audience(callback: CallbackQuery, state: FSMContext):
    mapping = {
        "announce_all": "all",
        "announce_paid": "paid",
        "announce_rfool": "rfool",
        "announce_others": "others"
    }
    selected = mapping.get(callback.data)

    if not selected:
        return await callback.answer("Ошибка")

    data = await state.get_data()
    msg: Message = data["msg"]

    await state.update_data(audience=selected)

    # 👇 Превью
    preview = await msg.copy_to(callback.from_user.id)

    # 👇 Подпись с группой
    await callback.message.answer(
        f"📨 <b>Группа:</b> {audience_label(selected)}\n\n"
        f"Отправляем это сообщение?",
        reply_markup=confirm_keyboard(),
        reply_to_message_id=preview.message_id,
        parse_mode="HTML"
    )

    await state.set_state(AnnounceState.confirm)
    await callback.answer()
def audience_label(audience: str) -> str:
    return {
        "all": "👥 Все пользователи",
        "paid": "💸 Те, кто оплатили",
        "rfool": "🌍 Те, кто хотели сменить регион (не оплатили)"
    }.get(audience, "Неизвестно")

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
    audience = data["audience"]

    users = await get_user_ids_by_state(audience) if not TEST_MODE else ADMIN_IDS

    if not users:
        await callback.message.edit_text("Нет пользователей")
        await state.clear()
        return

    await callback.message.edit_text("🚀 Начинаю рассылку...")

    total = len(users)
    success, failed = await mailer.send_to_many(users, msg)



    await callback.message.edit_text(
        f"✅ Готово\n\n"
        f"Всего: {total}\n"
        f"Отправлено: {success}\n"
        f"Ошибки: {failed}"
    )

    await state.clear()