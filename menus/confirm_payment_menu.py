from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config.utils import IsAdmin
from keyboards.webapp_buttons import payment_moved_keyboard

rt = Router()


@rt.message(Command("test10"), IsAdmin())
async def test_buy_10(message: Message):
    await message.answer(
        "Тестовые оплаты в боте отключены. Все оплаты теперь проходят в веб-приложении."
    )


# -------------------------
# CALLBACK
# -------------------------
@rt.callback_query(lambda c: c.data.startswith("pay/"))
async def process_payment(callback: CallbackQuery):
    _, service, _amount = callback.data.split("/")

    await callback.message.answer(
        "💳 Все оплаты теперь в веб-приложении:\n\n"
        "Откройте магазин по кнопке ниже, чтобы выбрать номинал и оплатить заказ.",
        reply_markup=payment_moved_keyboard(service),
    )

    await callback.answer()
