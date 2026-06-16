from aiogram import Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery

from keyboards.service_buttons import service_keyboard

from menus.deeplinks import handle_deeplink
from repository.database.database import add_client_source, add_referral
from services.media_cache import send_cached_photo


MAIN_MENU_PHOTO = "static/menus/as.png"

rt = Router()

@rt.message(CommandStart())
async def start(message: Message, command:CommandObject):
    payload = command.args
    if payload:
        # Составной payload "<меню>__<источник>": до "__" — ключ меню (callback_data),
        # после — источник (канал). Без "__" payload целиком и меню, и источник.
        if "__" in payload:
            menu_key, _, source = payload.partition("__")
        else:
            menu_key = source = payload

        # сначала фиксируем лид — откуда пришли (в т.ч. по deep-link на меню)
        if payload.startswith("ref"):
            await add_referral(
                telegram_id=message.from_user.id,
                payload=payload,
            )
        else:
            await add_client_source(
                telegram_id=message.from_user.id,
                payload=source
            )
        # deep-link на конкретное меню: menu_key == callback_data кнопки.
        # Совпало — показываем это меню первым сообщением и выходим.
        if await handle_deeplink(message, menu_key):
            return
    await show_main_menu(message)



@rt.callback_query(lambda c: c.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    await show_main_menu(callback)

async def show_main_menu(target: Message|CallbackQuery):

    text = ("<b>📱 Поможем оплатить ваши подписки App Store за 2 минуты!</b>\n\n"
            ""
            "С 1 апреля этого года оплачивать подписки в App Store в России через мобильного оператора стало невозможно\n\n"
            ""
            "<b>👉🏻 Но мы нашли решение:</b> сменить регион App Store на Турцию и пополнить аккаунт через подарочную карту, чтобы оплатить iCloud, Apple Music, Telegram Premium и другие подписки.\n\n"

            "Это безопасно, удобно и быстро. Уже 1000+ наших клиентов сделали это и пользуются любимыми приложениями без проблем. Как раньше, без блокировок.\n\n"
            ""
            "👩‍💻<b>Официальный сайт:</b> 2pay.money\n\n"
            "👤<b>Техническая поддержка:</b> @MANAGER_2PAY\n\n"
            
            "<b>🇹🇷 Мы поможем сменить регион и выдадим подарочную карту за 2 минуты. Выбирайте нужный раздел 👇</b>")
    if isinstance(target, Message):
        await send_cached_photo(target, MAIN_MENU_PHOTO, caption=text, reply_markup=service_keyboard("as"), parse_mode="html")

    elif isinstance(target, CallbackQuery):

        await send_cached_photo(target.message, MAIN_MENU_PHOTO, caption=text, reply_markup=service_keyboard("as"), parse_mode="html")
        await target.answer()







