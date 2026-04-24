from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from keyboards.service_buttons import service_keyboard

from aiogram.types import FSInputFile

from repository.database.database import add_client_source
from services.naeb_service import parse_start_payload

photo = FSInputFile("static/menus/as.png")

rt = Router()

@rt.message(CommandStart())
async def start(message: Message):
    payload = parse_start_payload(message)

    await add_client_source(
        telegram_id=message.from_user.id,
        payload=payload
    )
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
        await target.answer_photo( caption=text, photo=photo, reply_markup=service_keyboard("as"), parse_mode="html")

    elif isinstance(target, CallbackQuery):

        await target.message.answer_photo(caption=text, photo=photo, reply_markup=service_keyboard("as"), parse_mode="html")
        await target.answer()







