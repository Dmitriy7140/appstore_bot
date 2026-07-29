
from aiogram.types import CallbackQuery
from aiogram import Router
from keyboards.webapp_buttons import payment_moved_keyboard

rt = Router()


@rt.callback_query(lambda c: "/" in c.data and not c.data.startswith("pay/"))
async def handle_amount(callback: CallbackQuery):
    service, amount = callback.data.split("/")
    del amount

    await callback.message.answer(
        "💳 Все оплаты теперь в веб-приложении:\n\n"
        "Откройте магазин по кнопке ниже, чтобы выбрать номинал и оплатить заказ.",
        reply_markup=payment_moved_keyboard(service),
    )

    await callback.answer()
