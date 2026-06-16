"""
/menulink — генератор deep-link'ов для админа.

Шаг 1: выбрать пункт меню (куда поведёт ссылка) — кнопки берутся из главного меню,
        кроме кнопок с суммами пополнения (…:topup) и url-кнопок (без callback_data).
Шаг 2: ввести название ссылки (источник/канал).

Итог: payload = "<callback_data>__<название>", напр. asfaq_region__gibiscus,
и готовая ссылка t.me/<bot>?start=<payload>. Разбор payload — в menus/start.py:
до "__" выбирается меню, после "__" пишется источник в invite_links.
"""
import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.config_env import BOT_URL
from config.utils import IsAdmin
from keyboards.service_buttons import service_keyboard


router = Router()

# Telegram разрешает в start-параметре только A-Za-z0-9_- (до 64 символов суммарно).
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class MenuLinkState(StatesGroup):
    waiting_dest = State()   # ждём выбора пункта меню
    waiting_name = State()   # ждём ввода названия ссылки


def _dest_keyboard():
    """Кнопки = пункты главного меню, кроме сумм пополнения и url-кнопок."""
    builder = InlineKeyboardBuilder()
    for row in service_keyboard("as").inline_keyboard:
        for btn in row:
            if not btn.callback_data:           # url-кнопки (Отзывы) — нечего деплинкать
                continue
            if btn.callback_data.endswith(":topup"):   # суммы пополнения не нужны
                continue
            builder.button(text=btn.text, callback_data=f"mlink:{btn.callback_data}")
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("menulink"), IsAdmin())
async def menulink_start(message: Message, state: FSMContext):
    await message.answer(
        "🔗 <b>Генератор ссылок</b>\n\nКуда поведёт ссылка? Выбери пункт меню:",
        reply_markup=_dest_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(MenuLinkState.waiting_dest)


@router.callback_query(MenuLinkState.waiting_dest, F.data.startswith("mlink:"), IsAdmin())
async def menulink_pick_dest(callback: CallbackQuery, state: FSMContext):
    dest = callback.data.split(":", 1)[1]
    await state.update_data(dest=dest)
    await callback.message.answer(
        f"Пункт: <code>{dest}</code>\n\n"
        "Теперь введи <b>название ссылки</b> (источник/канал).\n"
        "Латиница, цифры, <code>_</code> и <code>-</code>, без пробелов.",
        parse_mode="HTML",
    )
    await state.set_state(MenuLinkState.waiting_name)
    await callback.answer()


@router.message(MenuLinkState.waiting_name, IsAdmin())
async def menulink_get_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not _NAME_RE.match(name):
        await message.answer("⚠️ Только латиница, цифры, _ и -, без пробелов. Попробуй ещё раз:")
        return

    data = await state.get_data()
    dest = data["dest"]
    payload = f"{dest}__{name}"

    if len(payload) > 64:
        await message.answer("⚠️ Слишком длинно (payload > 64 символов). Сократи название:")
        return

    url = f"{BOT_URL}?start={payload}"
    await message.answer(
        "✅ Готово!\n\n"
        f"Ссылка (нажми, чтобы скопировать):\n<code>{url}</code>\n\n"
        f"Пункт: <code>{dest}</code>\n"
        f"Источник в аналитике: <code>{name}</code>",
        parse_mode="HTML",
    )
    await state.clear()
