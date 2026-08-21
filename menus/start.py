import asyncio

from aiogram import Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from keyboards.menu_buttons import main_menu_keyboard

from menus.deeplinks import handle_deeplink
from config.config_env import TWO_PAY_API_START_TIMEOUT_SECONDS
from config.utils import logger
from services.two_pay_api_client import TwoPayApiError, register_bot_user
from services.two_pay_api_deep_links import queue_deep_link_event
from services.media_cache import send_cached_photo


MAIN_MENU_PHOTO = "static/menus/main_menu_2026.png"

rt = Router()

@rt.message(CommandStart())
async def start(message: Message, command:CommandObject, state: FSMContext):
    # /start — чистый выход из любого незавершённого FSM-флоу (напр. опроса)
    await state.clear()
    await _register_started_user(message)
    payload = command.args
    if payload:
        # Составной payload "<меню>__<источник>": до "__" — ключ меню (callback_data),
        # после — источник (канал). Без "__" payload целиком и меню, и источник.
        if "__" in payload:
            menu_key, _, source = payload.partition("__")
        else:
            menu_key = source = payload

        # API is the source of truth for attribution and referral binding. The
        # bot only separates the two payload kinds and posts a normalized event.
        if payload.startswith("ref_"):
            try:
                referrer_telegram_id = int(payload.removeprefix("ref_"))
                if referrer_telegram_id <= 0:
                    raise ValueError
            except ValueError:
                logger.warning("Ignoring malformed referral deep-link: %s", payload)
            else:
                queue_deep_link_event(
                    telegram_id=message.from_user.id,
                    link=payload,
                    is_ref=True,
                    referrer_telegram_id=referrer_telegram_id,
                )
        else:
            queue_deep_link_event(
                telegram_id=message.from_user.id,
                link=source,
                is_ref=False,
            )
        # deep-link на конкретное меню: menu_key == callback_data кнопки.
        # Совпало — показываем это меню первым сообщением и выходим.
        if await handle_deeplink(message, menu_key):
            return
    await show_main_menu(message)


async def _register_started_user(message: Message) -> None:
    """Create/update the API user before referral/source handling and menu output."""
    user = message.from_user
    if user is None:
        logger.warning("Could not register /start without a Telegram user")
        return
    try:
        await asyncio.wait_for(
            register_bot_user(user.id, user.username),
            timeout=TWO_PAY_API_START_TIMEOUT_SECONDS,
        )
    except (TwoPayApiError, TimeoutError) as error:
        # Telegram should stay usable during a short API outage. The failure is
        # visible in logs; a later /start safely retries the same upsert.
        logger.warning("Could not register Telegram user %s in 2PAY API: %s", user.id, error)



@rt.callback_query(lambda c: c.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    await show_main_menu(callback)

async def show_main_menu(target: Message|CallbackQuery):

    text = (
        "<b>📱 Поможем оплатить подписки App Store и пополнить PlayStation — за 2 минуты!</b>\n\n"
        "С 1 апреля 2026 в России больше нельзя оплачивать покупки в App Store через мобильного "
        "оператора, а иностранные карты не принимаются.\n\n"
        "<b>👉🏻 Решение простое:</b> сменить регион Apple ID (<b>Турция или США</b>) и пополнить "
        "аккаунт подарочным кодом — чтобы оплачивать iCloud, Apple Music, Telegram Premium и другие "
        "подписки. А для геймеров — коды <b>PlayStation</b> на игры и PS Plus.\n\n"
        "<b>Это безопасно, удобно и быстро.</b> Уже 1000+ клиентов пользуются любимыми сервисами как "
        "раньше, без блокировок.\n\n"
        "🛒 Открыть магазин — кнопка слева снизу\n"
        "🇹🇷🇺🇸 App Store: Турция и США — коды и смена региона\n"
        "🎮 PlayStation: коды на игры и подписки\n\n"
        "👩‍💻 <b>Официальный сайт</b>: 2pay.money\n"
        "👤 <b>Техническая поддержка:</b> @MANAGER_2PAY\n\n"
        "Выбирайте нужный раздел 👇"
    )
    if isinstance(target, Message):
        await send_cached_photo(
            target,
            MAIN_MENU_PHOTO,
            caption=text,
            reply_markup=main_menu_keyboard(),
            parse_mode="html",
        )

    elif isinstance(target, CallbackQuery):

        await send_cached_photo(
            target.message,
            MAIN_MENU_PHOTO,
            caption=text,
            reply_markup=main_menu_keyboard(),
            parse_mode="html",
        )
        await target.answer()







