
import asyncio

import uuid

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from yookassa import Configuration, Payment
from config.config_env import SHOP_ID, SECRET_KEY, BOT_URL
from config.utils import logger

from services.sender_service import send_transaction_notice
from main import bot
RATES = {1:1,
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
            "user_id": user_id,
        },
        "description": f"Оплата заказа user_id ({user_id})",

    },id_key )
    logger.info(f"создали транзакцию для айди {user_id}")
    return payment.confirmation.confirmation_url, payment.id



async def wait_payment(callback, get_key, payment_id):

    timeout = 11*60
    start_time= asyncio.get_event_loop().time()
    while True:
        if asyncio.get_event_loop().time() - start_time > timeout:
            await callback.message.answer("⌛ Время оплаты истекло")
            logger.error(f"Время оплаты истекло у {callback.from_user.id}")
            return
        payment = Payment.find_one(payment_id)

        if payment.status == "succeeded":
            key = get_key(int(payment.amount.value))

            await callback.message.answer( "✅ Оплата прошла! Вот ваш ключ:\n\n"
                                           f"<code>{key}</code>", parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Как активировать код?", callback_data="asfaq_code")],
                                                                                                                                       [InlineKeyboardButton(
                                                                                                                                           text="Как поменять регион?",
                                                                                                                                           callback_data="asfaq_region")]]))
            user_id = int(payment.metadata["user_id"])
            logger.info(f"Отправляем транзакцию для айди {user_id}")
            await send_transaction_notice(
                bot,
                telegram_id=user_id,
                tx_id=payment.id,
                amount=int(payment.amount.value),
                code=key
            )
            logger.info(f"Оплата подтверждена! user_id:{user_id}, amount:{payment.amount.value}")
            break
        if payment.status == "canceled":
            await callback.message.answer( "❌Платеж отменен. Попробуйте еще раз или свяжитесь с менеджером @MANAGER_2PAY")
            logger.error(f"Оплата была отменена! user_id:{callback.from_user.id}")
            break
        await asyncio.sleep(5)