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

    text = ("<b>📱 Поможем сменить регион в App Store с России на Турцию и пополнить за 2 минуты!</b>\n\n"

            "•Смена региона занимает 1 минуту по инструкции\n"
            "•Для пополнения вы покупаете подарочный код, активируете и оплачиваете всё как было до блокировок\n"
            "•Вход в ваш аккаунт не нужен\n"
            "•iCloud+ и все ваши данные будут в полной сохранности!\n"
            "•Поддержка менеджера 24/7\n\n"
            
            "Официальный сайт 2pay.money\n\n"
            
            "<b>🇹🇷 Мы поможем вам быстро сменить регион, пополнить Apple ID и вы снова сможете оплачивать нужные приложения, игры, подписки и iCloud без лишних сложностей 👇</b>")
    if isinstance(target, Message):
        await target.answer_photo( caption=text, photo=photo, reply_markup=service_keyboard("as"), parse_mode="html")

    elif isinstance(target, CallbackQuery):

        await target.message.answer_photo(caption=text, photo=photo, reply_markup=service_keyboard("as"), parse_mode="html")
        await target.answer()







