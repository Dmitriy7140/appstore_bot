import asyncio
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router
from services.payments import create_payment, wait_payment, RATES
from repository.sheets.sheets import sheets

rt = Router()
@rt.callback_query(lambda c: c.data.startswith("pay/"))
async def process_payment(callback: CallbackQuery):

    _, service, amount = callback.data.split("/")

    amount = int(amount)

    payment_url, payment_id = await create_payment(
        amount,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton(text="Прочти перед оплатой", callback_data="asfaq_payment")],
            [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")]
        ]
    )

    sent = await callback.message.answer(
        text=(
            f"К оплате {RATES[amount]} рублей\n\n"
            f"Ссылка для оплаты 👇\n\n"
            f"После оплаты дождитесь подтверждения ✅"
        ),
        reply_markup=keyboard
    )

    asyncio.create_task(
        wait_payment(
            callback,
            sheets.get_key,
            payment_id,
            sent
        )
    )

    await callback.answer()