from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router
from services.payments import create_payment
rt = Router()

@rt.callback_query(lambda c: "/" in c.data)
async def handle_amount(callback: CallbackQuery):
    service, amount = callback.data.split("/")

    if amount == "any":
        await callback.message.answer("💰Для указания своей суммы свяжитесь, пожалуйста, с менеджером @MANAGER_2PAY")
        await callback.answer()
        return

   # payment_url = await create_payment(service, int(amount))

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url="https://t.me/MANAGER_2PAY")],
            [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")]
        ]
    )

    await callback.message.answer(
        text=f"Вы выбрали {amount} лир\n\nПерейдите к оплате 👇",
        reply_markup=keyboard
    )

    await callback.answer()