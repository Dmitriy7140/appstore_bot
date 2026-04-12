from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from keyboards.menu_buttons import  main_menu_keyboard

rt = Router()

@rt.message(CommandStart())
async def start(message: Message):
    await show_main_menu(message)


@rt.callback_query(lambda c: c.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    await show_main_menu(callback)

async def show_main_menu(target: Message|CallbackQuery):
    text = ("🎮 Добро пожаловать!\n\n"

            "Пополняйте баланс быстро и без лишней головной боли 💸\n"
            "Мы поможем закинуть деньги на:\n\n"

            "🍏 App Store\n"
            "🤖 Google Play\n"
            "🎮 PlayStation\n"
            "🟢 Xbox\n"
            "💻 Steam\n\n"
            
            "Выбирайте платформу ниже и поехали 🚀")
    if isinstance(target, Message):
        await target.answer(text, reply_markup=main_menu_keyboard())

    elif isinstance(target, CallbackQuery):
        await target.message.answer(text, reply_markup=main_menu_keyboard())
        await target.answer()







