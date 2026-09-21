"""Button constructor for announcement posts and nested promotion posts."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from commands.menulink import menu_link_destinations
from config.config_env import ADMIN_IDS
from config.utils import IsAdmin, logger
from keyboards.webapp_buttons import WEB_APP_URL
from repository.sqlite_storage import get_repository
from services.announcement_posts import (
    MAX_BUTTONS, PROMO_CALLBACK_PREFIX, button_count, copy_post, draft_post,
    valid_button_url,
)
from services.tg_retry import send_flood_safe


router = Router()


class AnnounceState(StatesGroup):
    choosing_mode = State()
    choosing_day = State()
    waiting_time = State()
    waiting_message = State()
    buttons = State()
    button_type = State()
    button_menu = State()
    button_url = State()
    button_title = State()
    promotion_message = State()
    waiting_audience = State()
    confirm = State()


def audience_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Все", callback_data="announce_all")
    builder.button(text="💸 Оплатили", callback_data="announce_paid")
    builder.button(text="🤪 Не оплатили", callback_data="announce_never_paid")
    builder.adjust(1)
    return builder.as_markup()


def back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Отменить добавление кнопки", callback_data="ann_build_back")
    return builder.as_markup()


async def begin_post(message: Message, state: FSMContext):
    post = draft_post(message)
    await state.update_data(
        root_post_id=post["id"], post_drafts={post["id"]: post},
        builder_stack=[{"post_id": post["id"]}], preview_ready=False,
    )
    await show_buttons(message, state)


async def show_buttons(message: Message, state: FSMContext):
    data = await state.get_data()
    post = data["post_drafts"][data["builder_stack"][-1]["post_id"]]
    count = button_count(post)
    builder = InlineKeyboardBuilder()
    if count < MAX_BUTTONS:
        builder.button(text="➕ Добавить кнопку" if not count else "➕ Добавить ещё", callback_data="ann_build_add")
    builder.button(text="Без новых кнопок" if not count else "✅ Хватит", callback_data="ann_build_done")
    if count:
        builder.button(text="↩️ Удалить последнюю кнопку", callback_data="ann_build_undo")
    nested = len(data["builder_stack"]) > 1
    builder.button(
        text="❌ Отменить акцию" if nested else "❌ Отменить рассылку",
        callback_data="ann_build_cancel",
    )
    builder.adjust(1)
    subject = "К посту акции" if nested else "К посту рассылки"
    text = f"{subject}: добавим кнопки?" if not count else (
        f"{subject} добавлено кнопок: {count}/{MAX_BUTTONS}.\nДобавить ещё или хватит?"
    )
    if count >= MAX_BUTTONS:
        text += "\nДостигнут предел кнопок для одного сообщения."
    await state.update_data(preview_ready=False)
    await state.set_state(AnnounceState.buttons)
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(AnnounceState.buttons, F.data == "ann_build_add", IsAdmin())
async def choose_button_type(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    post = data["post_drafts"][data["builder_stack"][-1]["post_id"]]
    if button_count(post) >= MAX_BUTTONS:
        await callback.answer("Достигнут предел кнопок", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for kind, label in (
        ("menu", "📋 Пункт меню"), ("url", "🔗 Ссылка"),
        ("tma", "🛒 ТМА — открыть приложение"), ("promo", "🎁 Добавить акцию"),
    ):
        builder.button(text=label, callback_data=f"ann_build_type:{kind}")
    builder.button(text="⬅️ Назад", callback_data="ann_build_back")
    builder.adjust(1)
    await state.set_state(AnnounceState.button_type)
    await callback.message.edit_text("Какую кнопку добавим?", reply_markup=builder.as_markup())
    await callback.answer()


async def ask_title(message: Message, state: FSMContext, button: dict, default_title: str):
    await state.update_data(pending_button=button, default_button_title=default_title)
    builder = InlineKeyboardBuilder()
    builder.button(text=default_title, callback_data="ann_build_default_title")
    builder.button(text="⬅️ Отменить добавление кнопки", callback_data="ann_build_back")
    builder.adjust(1)
    await state.set_state(AnnounceState.button_title)
    await message.answer(
        "Как назовём кнопку? Отправьте текст (до 64 символов) или выберите название ниже.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(AnnounceState.button_type, F.data.startswith("ann_build_type:"), IsAdmin())
async def select_button_type(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.rsplit(":", 1)[1]
    await callback.answer()
    if kind == "menu":
        builder = InlineKeyboardBuilder()
        for button in menu_link_destinations():
            builder.button(text=button.text, callback_data=f"ann_build_menu:{button.callback_data}")
        builder.button(text="⬅️ Назад", callback_data="ann_build_back")
        builder.adjust(1)
        await callback.message.edit_text("Куда ведёт кнопка?", reply_markup=builder.as_markup())
        await state.set_state(AnnounceState.button_menu)
    elif kind == "url":
        await callback.message.edit_text(
            "Пришлите ссылку, которую встроим в кнопку (https://, http:// или tg://).",
            reply_markup=back_keyboard(),
        )
        await state.set_state(AnnounceState.button_url)
    elif kind == "tma":
        await ask_title(callback.message, state, {"web_app": {"url": WEB_APP_URL}}, "🛒 Открыть приложение")
    elif kind == "promo":
        await callback.message.edit_text(
            "Пришлите условия акции одним сообщением: текст или медиа с подписью. "
            "Ссылки и форматирование сохранятся. Затем добавим кнопки к этому посту.",
            reply_markup=back_keyboard(),
        )
        await state.set_state(AnnounceState.promotion_message)


@router.callback_query(AnnounceState.button_menu, F.data.startswith("ann_build_menu:"), IsAdmin())
async def select_menu(callback: CallbackQuery, state: FSMContext):
    destination = callback.data.split(":", 1)[1]
    button = next((b for b in menu_link_destinations() if b.callback_data == destination), None)
    if button is None:
        await callback.answer("Этот пункт меню недоступен", show_alert=True)
        return
    await ask_title(callback.message, state, {"callback_data": destination}, button.text)
    await callback.answer()


@router.message(AnnounceState.button_url, IsAdmin())
async def receive_url(message: Message, state: FSMContext):
    url = (message.text or "").strip()
    if not valid_button_url(url):
        await message.answer("Не удалось распознать ссылку. Пришлите полный адрес, например https://example.com.")
        return
    await ask_title(message, state, {"url": url}, "Открыть ссылку")


@router.message(AnnounceState.promotion_message, IsAdmin())
async def receive_promotion(message: Message, state: FSMContext):
    data = await state.get_data()
    post = draft_post(message)
    data["post_drafts"][post["id"]] = post
    await state.update_data(post_drafts=data["post_drafts"])
    await ask_title(
        message, state, {"callback_data": PROMO_CALLBACK_PREFIX + post["id"]}, "🎁 Условия акции",
    )


async def add_titled_button(message: Message, state: FSMContext, title: str):
    data = await state.get_data()
    button = {**data["pending_button"], "text": title}
    callback = button.get("callback_data", "")
    if callback.startswith(PROMO_CALLBACK_PREFIX):
        data["builder_stack"].append({
            "post_id": callback.removeprefix(PROMO_CALLBACK_PREFIX), "parent_button": button,
        })
    else:
        post = data["post_drafts"][data["builder_stack"][-1]["post_id"]]
        if button_count(post) >= MAX_BUTTONS:
            await show_buttons(message, state)
            return
        post["reply_markup"]["inline_keyboard"].append([button])
    await state.update_data(
        post_drafts=data["post_drafts"], builder_stack=data["builder_stack"], pending_button=None,
    )
    await show_buttons(message, state)


@router.message(AnnounceState.button_title, IsAdmin())
async def receive_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title or len(title) > 64 or "\n" in title:
        await message.answer("Пришлите название кнопки одной строкой, от 1 до 64 символов.")
        return
    await add_titled_button(message, state, title)


@router.callback_query(AnnounceState.button_title, F.data == "ann_build_default_title", IsAdmin())
async def default_title(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await add_titled_button(callback.message, state, data["default_button_title"])
    await callback.answer()


@router.callback_query(AnnounceState.buttons, F.data == "ann_build_undo", IsAdmin())
async def undo_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    rows = data["post_drafts"][data["builder_stack"][-1]["post_id"]]["reply_markup"]["inline_keyboard"]
    if rows:
        rows[-1].pop()
        if not rows[-1]:
            rows.pop()
    await state.update_data(post_drafts=data["post_drafts"])
    await show_buttons(callback.message, state)
    await callback.answer()


@router.callback_query(AnnounceState.buttons, F.data == "ann_build_done", IsAdmin())
async def finish_buttons(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await callback.answer()
    if len(data["builder_stack"]) > 1:
        frame = data["builder_stack"][-1]
        post = data["post_drafts"][frame["post_id"]]
        try:
            await send_flood_safe(lambda: copy_post(callback.bot, callback.from_user.id, post))
        except (TelegramBadRequest, TelegramForbiddenError):
            await callback.message.answer("Не удалось показать пост акции. Проверьте исходное сообщение или отмените акцию и пришлите её заново.")
            return
        data["builder_stack"].pop()
        parent = data["post_drafts"][data["builder_stack"][-1]["post_id"]]
        parent["reply_markup"]["inline_keyboard"].append([frame["parent_button"]])
        await state.update_data(post_drafts=data["post_drafts"], builder_stack=data["builder_stack"])
        await callback.message.answer("Пост акции готов. Возвращаемся к кнопкам предыдущего поста.")
        await show_buttons(callback.message, state)
    else:
        await callback.message.answer("Кому отправить?", reply_markup=audience_keyboard())
        await state.set_state(AnnounceState.waiting_audience)


@router.callback_query(
    AnnounceState.button_type, F.data == "ann_build_back", IsAdmin(),
)
@router.callback_query(AnnounceState.button_menu, F.data == "ann_build_back", IsAdmin())
@router.callback_query(AnnounceState.button_url, F.data == "ann_build_back", IsAdmin())
@router.callback_query(AnnounceState.button_title, F.data == "ann_build_back", IsAdmin())
@router.callback_query(AnnounceState.promotion_message, F.data == "ann_build_back", IsAdmin())
async def cancel_button(callback: CallbackQuery, state: FSMContext):
    await state.update_data(pending_button=None)
    await show_buttons(callback.message, state)
    await callback.answer()


@router.callback_query(AnnounceState.buttons, F.data == "ann_build_cancel", IsAdmin())
async def cancel_builder(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if len(data["builder_stack"]) > 1:
        data["builder_stack"].pop()
        await state.update_data(builder_stack=data["builder_stack"])
        await show_buttons(callback.message, state)
    else:
        await state.clear()
        await callback.message.edit_text("❌ Рассылка отменена")
    await callback.answer()


@router.callback_query(F.data.startswith(PROMO_CALLBACK_PREFIX))
async def open_promotion(callback: CallbackQuery, state: FSMContext):
    post_id = callback.data.removeprefix(PROMO_CALLBACK_PREFIX)
    post = await get_repository().get_announcement_post(post_id)
    if post is None and callback.from_user.id in ADMIN_IDS:
        data = await state.get_data()
        post = data.get("post_drafts", {}).get(post_id)
    if post is None:
        await callback.answer("Эта акция недоступна", show_alert=True)
        return
    await callback.answer()
    try:
        await send_flood_safe(lambda: copy_post(callback.bot, callback.from_user.id, post))
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.exception("Could not show announcement promotion %s", post_id)
        if callback.message:
            await callback.message.answer("Не удалось открыть условия акции. Попробуйте позже.")
