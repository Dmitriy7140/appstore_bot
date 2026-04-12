RATES = {
    500: 1500,
    1000: 3000,
    1250: 3750,
    1500: 4500,
    1750: 5250,
    2000: 6000,
}
SERVICE_NAMES = {
    "as" : "AppStore",
    "gp" : "Googleplay",
    "ps" : "Playstation",
    "st" : "Steam",
    "xb" : "Xbox"
}

import uuid
from yookassa import Configuration, Payment
from config.config_env import SHOP_ID, SECRET_KEY, BOT_URL

Configuration.account_id = SHOP_ID
Configuration.secret_key = SECRET_KEY


async def create_payment(service: str, amount: int) -> str:
    payment = Payment.create({
        "amount": {
            "value": str(RATES[amount]),
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/appstore_cash_bot"
        },
        "capture": True,
        "description": f"{SERVICE_NAMES[service]} пополнение на {RATES[amount]}",
    }, uuid.uuid4())

    return payment.confirmation.confirmation_url