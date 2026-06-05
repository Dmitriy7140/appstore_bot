from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from services.payments import create_payment, RATES

rt = Router()


# -------------------------
# CALLBACK
# -------------------------
# Создаём платёж и отдаём ссылку. Подтверждение оплаты и выдача ключа
# происходят асинхронно в webhook'е ЮKassa (services/yookassa_webhook.py).
# chat_id/user_id уезжают в metadata платежа и возвращаются в уведомлении.
@rt.callback_query(lambda c: c.data.startswith("pay/"))
async def process_payment(callback: CallbackQuery):

    _, service, amount = callback.data.split("/")
    amount = int(amount)

    payment_url, _payment_id = await create_payment(
        amount,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="Прочти перед оплатой", callback_data="asfaq_payment")],
        [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")]
    ])

    await callback.message.answer(
        f"К оплате {RATES[amount]} рублей\n\n"
        f"Ссылка для оплаты 👇\n\n"
        f"После оплаты дождитесь подтверждения ✅",
        reply_markup=keyboard
    )

    await callback.answer()
