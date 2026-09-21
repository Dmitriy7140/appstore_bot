import re
from datetime import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from commands.announcement_builder import (
    AnnounceState, audience_keyboard, begin_post, router as builder_router, show_buttons,
)
from config.config_env import ADMIN_IDS, TEST_MODE
from config.utils import IsAdmin
from repository.sqlite_storage import get_repository
from services.notification_service import Mailer
from services.announcement_posts import copy_post, post_markup, reachable_posts
from services.scheduler import remove_announcement_job, schedule_announcement_job
from services.tg_retry import send_flood_safe
from services.two_pay_api_client import get_audience


router = Router()
router.include_router(builder_router)

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
DAY_PREPOSITIONS = (
    "В понедельник", "Во вторник", "В среду", "В четверг",
    "В пятницу", "В субботу", "В воскресенье",
)
RECOMMENDED_GAP_MINUTES = 60
TIME_STEP_MINUTES = 10
TIMES_PER_PAGE = 24
TIME_PAGE_COUNT = 24 * 60 // TIME_STEP_MINUTES // TIMES_PER_PAGE
POSTS_PER_PAGE = 8
AUDIENCE_CALLBACKS = {
    "announce_all": "all",
    "announce_paid": "paid",
    "announce_never_paid": "never_paid",
}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


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
    builder.button(text="✏️ Изменить кнопки", callback_data="announce_edit_buttons")
    builder.adjust(2, 1)
    return builder.as_markup()


def weekdays_keyboard(announcements: list[dict]):
    builder = InlineKeyboardBuilder()
    for weekday, day_name in enumerate(DAY_NAMES):
        items = [item for item in announcements if item["weekday"] == weekday]
        suffix = f" — {len(items)} шт." if items else ""
        builder.button(
            text=f"{day_name}{suffix}",
            callback_data=f"announce_weekday:{weekday}",
        )
    builder.button(text="⬅️ Назад", callback_data="announce_back_to_mode")
    builder.adjust(1)
    return builder.as_markup()


def existing_day_keyboard(weekday: int, announcements: list[dict], page: int = 0):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕ Добавить ещё", callback_data=f"announce_add:{weekday}",
    )
    builder.adjust(1)
    for index, item in enumerate(
        announcements[page * POSTS_PER_PAGE:(page + 1) * POSTS_PER_PAGE],
        start=page * POSTS_PER_PAGE + 1,
    ):
        row = InlineKeyboardBuilder()
        row.button(
            text=f"✏️ {index}. {item['send_time'].strftime('%H:%M')}",
            callback_data=f"announce_edit_post:{item['id']}",
        )
        row.button(text=f"🗑 {index}", callback_data=f"announce_delete_post:{item['id']}")
        builder.row(*row.buttons)
    navigation = InlineKeyboardBuilder()
    if page > 0:
        navigation.button(text="⬅️", callback_data=f"announce_day_page:{weekday}:{page - 1}")
    if (page + 1) * POSTS_PER_PAGE < len(announcements):
        navigation.button(text="➡️", callback_data=f"announce_day_page:{weekday}:{page + 1}")
    if list(navigation.buttons):
        builder.row(*navigation.buttons)
    back = InlineKeyboardBuilder()
    back.button(text="⬅️ К дням недели", callback_data="announce_back_to_days")
    builder.row(*back.buttons)
    return builder.as_markup()


def has_time_conflict(weekday: int, send_time: time, announcements: list[dict]) -> bool:
    candidate = weekday * 1440 + send_time.hour * 60 + send_time.minute
    week_minutes = 7 * 1440
    for item in announcements:
        other = item["weekday"] * 1440 + item["send_time"].hour * 60 + item["send_time"].minute
        distance = abs(candidate - other)
        if min(distance, week_minutes - distance) < RECOMMENDED_GAP_MINUTES:
            return True
    return False


def recommended_time(weekday: int, announcements: list[dict]) -> time | None:
    same_day = [item["send_time"] for item in announcements if item["weekday"] == weekday]
    start = 10 * 60
    if same_day:
        latest = max(same_day)
        start = latest.hour * 60 + latest.minute + RECOMMENDED_GAP_MINUTES
    # Round up to the button grid, then look for a free hour on this day.
    start = ((start + TIME_STEP_MINUTES - 1) // TIME_STEP_MINUTES) * TIME_STEP_MINUTES
    for offset in range(0, 1440, TIME_STEP_MINUTES):
        minutes = (start + offset) % 1440
        candidate = time(minutes // 60, minutes % 60)
        if not has_time_conflict(weekday, candidate, announcements):
            return candidate
    return None


def time_keyboard(weekday: int, announcements: list[dict], page: int):
    builder = InlineKeyboardBuilder()
    recommended = recommended_time(weekday, announcements)
    start = page * TIMES_PER_PAGE * TIME_STEP_MINUTES
    for minutes in range(start, start + TIMES_PER_PAGE * TIME_STEP_MINUTES, TIME_STEP_MINUTES):
        value = time(minutes // 60, minutes % 60)
        label = value.strftime("%H:%M")
        if has_time_conflict(weekday, value, announcements):
            label = f"⏳ {label}"
        elif value == recommended:
            label = f"✅ {label}"
        builder.button(text=label, callback_data=f"announce_time:{value.strftime('%H:%M')}")
    builder.adjust(4)
    navigation = InlineKeyboardBuilder()
    if page > 0:
        navigation.button(text="⬅️", callback_data=f"announce_time_page:{page - 1}")
    navigation.button(text=f"{page + 1}/{TIME_PAGE_COUNT}", callback_data="announce_time_info")
    if page + 1 < TIME_PAGE_COUNT:
        navigation.button(text="➡️", callback_data=f"announce_time_page:{page + 1}")
    builder.row(*navigation.buttons)
    back = InlineKeyboardBuilder()
    back.button(text="⬅️ К дням недели", callback_data="announce_back_to_days")
    builder.row(*back.buttons)
    return builder.as_markup()


def post_preview(message: Message) -> str:
    text = " ".join((message.text or message.caption or "").split())
    if not text:
        text = {
            "photo": "Фото без подписи", "video": "Видео без подписи",
            "document": "Документ без подписи", "animation": "Анимация без подписи",
        }.get(message.content_type, "Сообщение без текста")
    return text if len(text) <= 80 else text[:77] + "…"


async def show_day(message: Message, weekday: int, page: int = 0) -> None:
    announcements = await get_repository().list_schedules(weekday)
    page = max(0, min(page, (len(announcements) - 1) // POSTS_PER_PAGE))
    text = f"{DAY_PREPOSITIONS[weekday]} уже есть рассылка:" if len(announcements) == 1 else (
        f"{DAY_PREPOSITIONS[weekday]} уже есть рассылки:" if announcements else
        f"{DAY_PREPOSITIONS[weekday]} пока нет рассылок."
    )
    for index, item in enumerate(
        announcements[page * POSTS_PER_PAGE:(page + 1) * POSTS_PER_PAGE],
        start=page * POSTS_PER_PAGE + 1,
    ):
        preview = item["post_preview"] or f"Сообщение №{item['source_message_id']}"
        text += f"\n{index}. {item['send_time'].strftime('%H:%M')} — пост «{preview}»"
    text += "\n\nВремя — МСК. Добавить ещё?" if announcements else "\n\nДобавить рассылку?"
    await message.edit_text(
        text, reply_markup=existing_day_keyboard(weekday, announcements, page), parse_mode=None,
    )


async def show_times(message: Message, state: FSMContext, page: int | None = None) -> None:
    data = await state.get_data()
    weekday = data["weekday"]
    announcements = [
        item for item in await get_repository().list_schedules()
        if item["id"] != data.get("schedule_id")
    ]
    suggested = recommended_time(weekday, announcements)
    if page is None:
        current = parse_time(data.get("send_time") or "") or suggested or time(0)
        page = (current.hour * 60 + current.minute) // (TIMES_PER_PAGE * TIME_STEP_MINUTES)
    page = max(0, min(page, TIME_PAGE_COUNT - 1))
    text = (
        f"Выберите время: {DAY_NAMES[weekday]} (МСК).\n"
        "Оставляйте 40–60 минут между рассылками; рекомендуем запас в 1 час.\n"
        "⏳ — до соседней рассылки меньше часа. Выбрать это время тоже можно: "
        "при пересечении пост дождётся завершения предыдущей рассылки.\n\n"
        "Можно ввести любое время вручную в формате ЧЧ:ММ."
    )
    if suggested:
        text += f"\nРекомендуем: {suggested.strftime('%H:%M')}."
    await message.edit_text(text, reply_markup=time_keyboard(weekday, announcements, page))
    await state.set_state(AnnounceState.waiting_time)


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
        "В один день можно добавить несколько постов. "
        "У каждого поста своё время; его можно изменить или удалить отдельно."
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
    AnnounceState.waiting_time,
    F.data == "announce_back_to_days",
    IsAdmin(),
)
@router.callback_query(
    AnnounceState.choosing_day,
    F.data == "announce_back_to_days",
    IsAdmin(),
)
async def back_to_weekdays(callback: CallbackQuery, state: FSMContext):
    await state.update_data(schedule_id=None, weekday=None, send_time=None)
    await show_weekdays(callback.message, edit=True)
    await state.set_state(AnnounceState.choosing_day)
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

    await state.update_data(weekday=weekday, schedule_id=None, send_time=None)
    existing = await get_repository().list_schedules(weekday)
    if existing:
        await show_day(callback.message, weekday)
    else:
        await show_times(callback.message, state)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day, F.data.startswith("announce_day_page:"), IsAdmin(),
)
async def paginate_day(callback: CallbackQuery):
    _, weekday, page = callback.data.split(":")
    if int(weekday) not in range(7):
        await callback.answer("Некорректный день", show_alert=True)
        return
    await show_day(callback.message, int(weekday), int(page))
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day, F.data.startswith("announce_add:"), IsAdmin(),
)
async def add_scheduled_post(callback: CallbackQuery, state: FSMContext):
    weekday = int(callback.data.rsplit(":", 1)[1])
    if weekday not in range(7):
        await callback.answer("Некорректный день", show_alert=True)
        return
    await state.update_data(weekday=weekday, schedule_id=None, send_time=None)
    await show_times(callback.message, state)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day,
    F.data.startswith(("announce_change:", "announce_delete:")),
    IsAdmin(),
)
async def legacy_day_action(callback: CallbackQuery, state: FSMContext):
    # Buttons sent before the migration contain a weekday, not a post ID.
    await back_to_weekdays(callback, state)


@router.callback_query(
    AnnounceState.choosing_day,
    F.data.startswith("announce_edit_post:"),
    IsAdmin(),
)
async def change_scheduled_day(callback: CallbackQuery, state: FSMContext):
    schedule_id = int(callback.data.rsplit(":", 1)[1])
    announcement = await get_repository().get_schedule(schedule_id)
    if announcement is None:
        await callback.answer("Этот пост уже удалён", show_alert=True)
        return
    await state.update_data(
        weekday=announcement["weekday"], schedule_id=schedule_id,
        send_time=announcement["send_time"].strftime("%H:%M"),
    )
    await show_times(callback.message, state)
    await callback.answer()


@router.callback_query(
    AnnounceState.choosing_day,
    F.data.startswith("announce_delete_post:"),
    IsAdmin(),
)
async def delete_scheduled_day(
    callback: CallbackQuery,
    state: FSMContext,
    scheduler: AsyncIOScheduler,
):
    schedule_id = int(callback.data.rsplit(":", 1)[1])
    announcement = await get_repository().get_schedule(schedule_id)
    deleted = await get_repository().delete_schedule(schedule_id)
    remove_announcement_job(scheduler, schedule_id)
    await state.update_data(schedule_id=None, send_time=None)
    if announcement:
        await show_day(callback.message, announcement["weekday"])
    else:
        await show_weekdays(callback.message, edit=True)
    await callback.answer("Запись удалена" if deleted else "Запись уже удалена")


@router.callback_query(
    AnnounceState.waiting_time, F.data.startswith("announce_time_page:"), IsAdmin(),
)
async def paginate_times(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.rsplit(":", 1)[1])
    await show_times(callback.message, state, page)
    await callback.answer()


@router.callback_query(
    AnnounceState.waiting_time, F.data == "announce_time_info", IsAdmin(),
)
async def time_page_info(callback: CallbackQuery):
    await callback.answer("Листайте стрелками или введите время вручную")


async def accept_time(message: Message, state: FSMContext, send_time: time) -> None:
    data = await state.get_data()
    announcements = [
        item for item in await get_repository().list_schedules()
        if item["id"] != data.get("schedule_id")
    ]
    await state.update_data(send_time=send_time.strftime("%H:%M"))
    text = f"Выбрано время {send_time.strftime('%H:%M')} (МСК).\n"
    if has_time_conflict(data["weekday"], send_time, announcements):
        text += (
            "⏳ До соседней рассылки меньше часа. Если предыдущая ещё отправляется, "
            "этот пост встанет в очередь.\n"
        )
    await message.answer(text + "Теперь отправьте сообщение для рассылки.")
    await state.set_state(AnnounceState.waiting_message)


@router.callback_query(
    AnnounceState.waiting_time, F.data.startswith("announce_time:"), IsAdmin(),
)
async def choose_time(callback: CallbackQuery, state: FSMContext):
    send_time = parse_time(callback.data.split(":", 1)[1])
    if send_time is None:
        await callback.answer("Некорректное время", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await accept_time(callback.message, state, send_time)
    await callback.answer()


@router.message(AnnounceState.waiting_time, IsAdmin())
async def announce_get_time(message: Message, state: FSMContext):
    send_time = parse_time(message.text or "")
    if send_time is None:
        await message.answer(
            "Не удалось распознать время. Введите его в формате ЧЧ:ММ, например 09:30."
        )
        return

    await accept_time(message, state, send_time)


@router.message(AnnounceState.waiting_message, IsAdmin())
async def announce_get_message(message: Message, state: FSMContext):
    # Keep Telegram identifiers and serializable button drafts in SQLite FSM.
    await state.update_data(
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
        post_preview=post_preview(message),
    )
    await begin_post(message, state)


@router.callback_query(
    AnnounceState.waiting_audience,
    F.data.in_(AUDIENCE_CALLBACKS),
    IsAdmin(),
)
async def announce_get_audience(callback: CallbackQuery, state: FSMContext):
    selected = AUDIENCE_CALLBACKS[callback.data]
    data = await state.get_data()
    await state.update_data(audience=selected)

    if not data.get("root_post_id"):
        await callback.answer("Начните создание поста заново через /announce", show_alert=True)
        return
    post = data["post_drafts"][data["root_post_id"]]
    await callback.answer()
    try:
        preview = await send_flood_safe(
            lambda: copy_post(callback.bot, callback.from_user.id, post)
        )
    except (TelegramBadRequest, TelegramForbiddenError, ValueError):
        await callback.message.answer(
            "Не удалось показать предпросмотр. Пост не сохранён. "
            "Проверьте исходное сообщение и создайте рассылку заново через /announce."
        )
        return
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
    await state.update_data(preview_ready=True)
    await state.set_state(AnnounceState.confirm)


@router.callback_query(AnnounceState.confirm, F.data == "announce_edit_buttons", IsAdmin())
async def edit_draft_buttons(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(builder_stack=[{"post_id": data["root_post_id"]}])
    await show_buttons(callback.message, state)
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
    if not data.get("preview_ready"):
        await callback.message.answer("Сначала завершите конструктор и посмотрите предпросмотр поста.")
        return
    audience = data["audience"]
    source_chat_id = data["source_chat_id"]
    source_message_id = data["source_message_id"]
    posts = reachable_posts(data)
    root_post = data["post_drafts"][data["root_post_id"]]

    if data["delivery_mode"] == "scheduled":
        weekday = data["weekday"]
        send_time = parse_time(data["send_time"])
        try:
            announcement = await get_repository().put_schedule(
                weekday=weekday,
                send_time=send_time,
                audience=audience,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                created_by=callback.from_user.id,
                post_preview=data.get("post_preview", ""),
                schedule_id=data.get("schedule_id"),
                post_id=root_post["id"],
                posts=posts,
            )
        except LookupError:
            await callback.message.edit_text("Этот пост уже удалён. Создайте новую рассылку через /announce.")
            await state.clear()
            return
        schedule_announcement_job(scheduler, mailer, announcement)
        await callback.message.edit_text(
            "✅ Публикация сохранена и будет повторяться каждую неделю.\n\n"
            f"День: {DAY_NAMES[weekday]}\n"
            f"Время: {data['send_time']} (МСК)\n"
            f"Группа: {audience_label(audience)}\n\n"
            "Если предыдущая рассылка не успеет завершиться, этот пост дождётся её в очереди."
        )
        await state.clear()
        return

    async def load_audience():
        return await get_audience(audience) if not TEST_MODE else ADMIN_IDS

    await get_repository().save_announcement_posts(posts, callback.from_user.id)
    await callback.message.edit_text(
        "🚀 Рассылка добавлена в очередь. Отправка начнётся после завершения предыдущих рассылок."
    )
    success, failed = await mailer.send_copy_to_many(
        load_audience,
        source_chat_id,
        source_message_id,
        reply_markup=post_markup(root_post),
    )
    total = success + failed
    await callback.message.edit_text(
        "✅ Готово\n\n"
        f"Всего: {total}\n"
        f"Отправлено: {success}\n"
        f"Ошибки: {failed}"
        if total else "Нет пользователей"
    )
    await state.clear()
