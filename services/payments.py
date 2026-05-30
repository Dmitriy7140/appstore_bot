
import uuid

from yookassa import Configuration, Payment, Receipt
from config.config_env import SHOP_ID, SECRET_KEY, BOT_URL
from config.utils import logger


RATES = {1: 1,
         100: 400.00,
         250: 950.00,
         500: 1750.00,
         1000: 3500.00,
         1250: 4250.00,
         1500: 5100.00,
         1750: 5600.00,
         2000: 6400.00,
         }
REV_RATES = {
    400: 100,
    950: 250,
    1750: 500,
    3500: 1000,
    4250: 1250,
    5100: 1500,
    5600: 1750,
    6400: 2000,
}
SERVICE_NAMES = {
    "as": "AppStore",
    "gp": "Googleplay",
    "ps": "Playstation",
    "st": "Steam",
    "xb": "Xbox"
}

Configuration.account_id = SHOP_ID
Configuration.secret_key = SECRET_KEY


async def create_payment(amount: int, chat_id, user_id) -> tuple:
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
        "receipt" : {
            "customer": {
                "email": "support2pay@gmail.com"
            },
            "items": [{
                "description": "Цифровой информационный материал",
                "quantity": "1.00",
                "amount": {
                    "value": f"{str(RATES[amount])}",
                    "currency": "RUB"
                },
                "vat_code": 1,
                "payment_subject": "service",
                "payment_mode": "full_prepayment"
            }]},

        "description": f"Оплата заказа user_id ({user_id})",

    }, id_key)
    # res = Receipt.create({
    #     "customer": {
    #         "email": "support2pay@gmail.com"
    #     },
    #     "type": "payment",
    #     "payment_id": f"{payment.id}",
    #     "on_behalf_of": f"{SHOP_ID}",
    #     "send": True,
    #     "items": [
    #         {
    #             "description": "Цифровой информационный материал",
    #             "quantity": "1.00",
    #             "amount": {
    #                 "value": f"{str(RATES[amount])}",
    #                 "currency": "RUB"
    #             },
    #             "vat_code": 1,
    #             "payment_mode": "full_prepayment",
    #             "payment_subject": "commodity"
    #         }
    #     ],
    #     "tax_system_code": 1,
    #     "settlements": [
    #         {
    #             "type": "cashless",
    #             "amount": {
    #                 "value": f"{str(RATES[amount])}",
    #                 "currency": "RUB"
    #             }
    #         }
    #     ]
    # })
    logger.info(f"создали транзакцию для айди {user_id}")
    return payment.confirmation.confirmation_url, payment.id

