
import asyncio

import uuid

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from yookassa import Configuration, Payment
from config.config_env import SHOP_ID, SECRET_KEY, BOT_URL

RATES = {1:1,
    500: 1000.00,
    1000: 2000.00,
    1250: 2500.00,
    1500: 3000.00,
    1750: 3500.00,
    2000: 4000.00,
}
SERVICE_NAMES = {
    "as" : "AppStore",
    "gp" : "Googleplay",
    "ps" : "Playstation",
    "st" : "Steam",
    "xb" : "Xbox"
}


Configuration.account_id = SHOP_ID
Configuration.secret_key = SECRET_KEY


async def create_payment( amount: int, chat_id, user_id) -> tuple:
    id_key = str(uuid.uuid4())
    payment = Payment.create({
        "amount": {
            "value": str(RATES[amount]),
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": f"{BOT_URL}"
        },
        "capture": True,
        "metadata": {
            "chat_id": chat_id,
        },
        "description": f"Оплата заказа user_id ({user_id})",

    },id_key )

    return payment.confirmation.confirmation_url, payment.id



async def wait_payment(callback, get_key, payment_id):
    timeout = 11*60
    start_time= asyncio.get_event_loop().time()
    while True:
        if asyncio.get_event_loop().time() - start_time > timeout:
            await callback.message.answer("⌛ Время оплаты истекло")
            return
        payment = Payment.find_one(payment_id)

        if payment.status == "succeeded":
            key = get_key(int(payment.amount.value))

            await callback.message.answer( "✅ Оплата прошла! Вот ваш ключ:\n\n"
                                           f"<code>{key}</code>", parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Как активировать код?", callback_data="as_faq")]]))
            break
        if payment.status == "canceled":
            await callback.message.answer( "❌Платеж отменен. Попробуйте еще раз или свяжитесь с менеджером @MANAGER_2PAY")
            break
        await asyncio.sleep(5)