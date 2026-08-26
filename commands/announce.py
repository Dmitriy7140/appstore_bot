import re
from datetime import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.config_env import ADMIN_IDS, TEST_MODE
from config.utils import IsAdmin
from repository.sqlite_storage import get_repository
from services.notification_service import Mailer
from services.scheduler import remove_announcement_job, schedule_announcement_job
from services.two_pay_api_client import get_audience


router = Router()

DAY_NAMES = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
DAY_SCHEDULE_LABELS = (
    "по понедельникам",
    "по вторникам",
    "по средам",
    "по четвергам",
    "по пятницам",
    "по субботам",
    "по воскресеньям",
)
AUDIENCE_CALLBACKS = {
    "announce_all": "all",
    "announce_paid": "paid",
    "announce_never_paid": "never_paid",
}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AnnounceState(StatesGroup):
    choosing_mode = State()
    choosing_day = State()
    waiting_time = State()
    waiting_message = State()
    waiting_audience = State()
    confirm = State()


def delivery_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Отправить сейчас", callback_data="announce_mode_now")
    builder.button(
        text="Еженедельная публикация",
        callback_data="announce_mode_scheduled",
    )
    builder.adjust(1)
    return builder.as_markup()


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
    builder.button(
        text="🤪 Не оплатили",
        callback_data="announce_never_paid",
    )
    builder.adjust(1)
    return builder.as_markup()


def weekdays_keyboard(announcements: list[dict]):
    by_weekday = {item["weekday"]: item for item in announcements}
    builder = InlineKeyboardBuilder()
    for weekday, day_name in enumerate(DAY_NAMES):
        item = by_weekday.get(weekday)
        suffix = f" — {item['send_time'].strftime('%H:%M')}" if item else ""
        builder.button(
            text=f"{day_name}{suffix}",
            callback_data=f"announce_weekday:{weekday}",
        )
    builder.button(text="⬅️ Назад", callback_data="announce_back_to_mode")
    builder.adjust(1)
    return builder.as_markup()


def existing_day_keyboard(weekday: int):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Изменить",
        callback_data=f"announce_change:{weekday}",
    )
    builder.button(
        text="🗑 Удалить",
        callback_data=f"announce_delete:{weekday}",
    )
    builder.button(text="⬅️ Назад", callback_data="announce_back_to_days")
    builder.adjust(2, 1)
    return builder.as_markup()


def audience_label(audience: str) -> str:
    return {
        "all": "👥 Все пользователи",
        "paid": "💸 Те, кто оплатили",
        "never_paid": "🤪 Те, кто не оплатили",
    }.get(audience, "Неизвестно")


def parse_time(value: str) -> time | None:
    value = value.strip()
    if not TIME_PATTERN.fullmatch(value):
        return None
    hour, minute = map(int, value.split(":"))
    return time(hour=hour, minute=minute)


async def show_weekdays(message: Message, *, edit: bool = False) -> None:
    announcements = await get_repository().list_schedules()
    text = (
        "Выберите день недели. Время указано по Москве.\n\n"
        "Публикация повторяется каждую неделю, пока её не удалить. "
        "Если рядом с днём уже есть время, запись можно изменить или удалить."
    )
    markup = weekdays_keyboard(announcements)
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(Command("announce"), IsAdmin())
async def announce_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Выберите способ доставки публикации:",
        reply_markup=delivery_keyboard(),
    )
    await state.set_state(AnnounceState.choosing_mode)


@router.callback_query(
    AnnounceState.choosing_mode,
    F.data == "announce_mode_now",
    IsAdmin(),
)
async def choose_immediate_delivery(callback: CallbackQuery, state: FSMContext):
    await state.update_data(delivery_mode="now")
    await callback.message.edit_text("Отправьте сообщение для рассылки.")
    await state.set_state(AnnounceState.waiting_message)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_mode,
    F.data == "announce_mode_scheduled",
    IsAdmin(),
)
async def choose_scheduled_delivery(callback: CallbackQuery, state: FSMContext):
    await state.update_data(delivery_mode="scheduled")
    await show_weekdays(callback.message, edit=True)
    await state.set_state(AnnounceState.choosing_day)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day,
    F.data == "announce_back_to_mode",
    IsAdmin(),
)
async def back_to_delivery_mode(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Выберите способ доставки публикации:",
        reply_markup=delivery_keyboard(),
    )
    await state.set_state(AnnounceState.choosing_mode)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day,
    F.data == "announce_back_to_days",
    IsAdmin(),
)
async def back_to_weekdays(callback: CallbackQuery):
    await show_weekdays(callback.message, edit=True)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day,
    F.data.startswith("announce_weekday:"),
    IsAdmin(),
)
async def choose_weekday(callback: CallbackQuery, state: FSMContext):
    weekday = int(callback.data.rsplit(":", 1)[1])
    if weekday not in range(len(DAY_NAMES)):
        await callback.answer("Некорректный день", show_alert=True)
        return

    await state.update_data(weekday=weekday)
    existing = await get_repository().get_schedule(weekday)
    if existing:
        await callback.message.edit_text(
            f"{DAY_NAMES[weekday]} уже настроен на "
            f"{existing['send_time'].strftime('%H:%M')} (МСК).\n"
            f"Аудитория: {audience_label(existing['audience'])}.",
            reply_markup=existing_day_keyboard(weekday),
        )
    else:
        await callback.message.edit_text(
            f"Введите время для дня «{DAY_NAMES[weekday]}» в формате ЧЧ:ММ.\n"
            "Например: 10:30. Часовой пояс — Москва."
        )
        await state.set_state(AnnounceState.waiting_time)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day,
    F.data.startswith("announce_change:"),
    IsAdmin(),
)
async def change_scheduled_day(callback: CallbackQuery, state: FSMContext):
    weekday = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(weekday=weekday)
    await callback.message.edit_text(
        f"Введите новое время для дня «{DAY_NAMES[weekday]}» в формате ЧЧ:ММ.\n"
        "Например: 10:30. Часовой пояс — Москва."
    )
    await state.set_state(AnnounceState.waiting_time)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day,
    F.data.startswith("announce_delete:"),
    IsAdmin(),
)
async def delete_scheduled_day(
    callback: CallbackQuery,
    state: FSMContext,
    scheduler: AsyncIOScheduler,
):
    weekday = int(callback.data.rsplit(":", 1)[1])
    deleted = await get_repository().delete_schedule(weekday)
    remove_announcement_job(scheduler, weekday)
    await state.update_data(weekday=None)
    await show_weekdays(callback.message, edit=True)
    await callback.answer("Запись удалена" if deleted else "Запись уже удалена")


@router.message(AnnounceState.waiting_time, IsAdmin())
async def announce_get_time(message: Message, state: FSMContext):
    send_time = parse_time(message.text or "")
    if send_time is None:
        await message.answer(
            "Не удалось распознать время. Введите его в формате ЧЧ:ММ, например 09:30."
        )
        return

    await state.update_data(send_time=send_time.strftime("%H:%M"))
    await message.answer("Теперь отправьте сообщение для рассылки.")
    await state.set_state(AnnounceState.waiting_message)


@router.message(AnnounceState.waiting_message, IsAdmin())
async def announce_get_message(message: Message, state: FSMContext):
    # SQLite FSM data is JSON: keep only stable Telegram identifiers, not the
    # full aiogram Message object.
    await state.update_data(
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
    )
    await message.answer(
        "Кому отправить?",
        reply_markup=audience_keyboard(),
    )
    await state.set_state(AnnounceState.waiting_audience)


@router.callback_query(
    AnnounceState.waiting_audience,
    F.data.in_(AUDIENCE_CALLBACKS),
    IsAdmin(),
)
async def announce_get_audience(callback: CallbackQuery, state: FSMContext):
    selected = AUDIENCE_CALLBACKS[callback.data]
    data = await state.get_data()
    await state.update_data(audience=selected)

    preview = await callback.message.bot.copy_message(
        chat_id=callback.from_user.id,
        from_chat_id=data["source_chat_id"],
        message_id=data["source_message_id"],
    )
    if data["delivery_mode"] == "scheduled":
        weekday = data["weekday"]
        question = (
            f"Сохраняем еженедельную отправку {DAY_SCHEDULE_LABELS[weekday]} "
            f"в {data['send_time']} (МСК)? Она будет повторяться, пока вы её не удалите."
        )
    else:
        question = "Отправляем это сообщение сейчас?"

    await callback.message.answer(
        f"📨 <b>Группа:</b> {audience_label(selected)}\n\n{question}",
        reply_markup=confirm_keyboard(),
        reply_to_message_id=preview.message_id,
        parse_mode="HTML",
    )
    await state.set_state(AnnounceState.confirm)
    await callback.answer()


@router.callback_query(
    AnnounceState.confirm,
    F.data == "announce_no",
    IsAdmin(),
)
async def announce_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена")
    await callback.answer()


@router.callback_query(
    AnnounceState.confirm,
    F.data == "announce_yes",
    IsAdmin(),
)
async def announce_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    mailer: Mailer,
    scheduler: AsyncIOScheduler,
):
    await callback.answer()
    data = await state.get_data()
    audience = data["audience"]
    source_chat_id = data["source_chat_id"]
    source_message_id = data["source_message_id"]

    if data["delivery_mode"] == "scheduled":
        weekday = data["weekday"]
        send_time = parse_time(data["send_time"])
        announcement = await get_repository().put_schedule(
            weekday=weekday,
            send_time=send_time,
            audience=audience,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            created_by=callback.from_user.id,
        )
        schedule_announcement_job(scheduler, mailer, announcement)
        await callback.message.edit_text(
            "✅ Публикация сохранена и будет повторяться каждую неделю.\n\n"
            f"День: {DAY_NAMES[weekday]}\n"
            f"Время: {data['send_time']} (МСК)\n"
            f"Группа: {audience_label(audience)}"
        )
        await state.clear()
        return

    users = await get_audience(audience) if not TEST_MODE else ADMIN_IDS
    if not users:
        await callback.message.edit_text("Нет пользователей")
        await state.clear()
        return

    await callback.message.edit_text("🚀 Начинаю рассылку...")
    total = len(users)
    success, failed = await mailer.send_copy_to_many(
        users,
        source_chat_id,
        source_message_id,
    )
    await callback.message.edit_text(
        "✅ Готово\n\n"
        f"Всего: {total}\n"
        f"Отправлено: {success}\n"
        f"Ошибки: {failed}"
    )
    await state.clear()
