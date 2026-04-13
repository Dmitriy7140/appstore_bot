
import asyncio

import uuid
from yookassa import Configuration, Payment
from config.config_env import SHOP_ID, SECRET_KEY, BOT_URL

RATES = {
    500: 1500.00,
    1000: 3000.00,
    1250: 3750.00,
    1500: 4500.00,
    1750: 5250.00,
    2000: 6000.00,
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


async def create_payment(service: str, amount: int, chat_id) -> tuple:
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
        "description": f"{SERVICE_NAMES[service]} пополнение на {RATES[amount]} руб",

    },id_key )

    return payment.confirmation.confirmation_url, payment.id



async def wait_payment(callback, get_key, payment_id):
    while True:
        payment = Payment.find_one(payment_id)

        if payment.status == "succeeded":
            key = get_key()
            await callback.message.answer( "✅ Оплата прошла! Вот ваш ключ:\n\n"
                                           f"<code>{key}</code>", parse_mode="HTML")
            break
        if payment.status == "canceled":
            await callback.message.answer( "❌Платеж отменен. Попробуйте еще раз или свяжитесь с менеджером @MANAGER_2PAY")
            break
        await asyncio.sleep(5)