
import uuid, asyncio

from yookassa import Configuration, Payment
from config.config_env import SHOP_ID, SECRET_KEY, BOT_URL
from config.utils import logger

# Номиналы вынесены в общий модуль (их же использует касса Альфа-Банка).
# Реэкспортируем для обратной совместимости со старыми импортами.
from services.rates import RATES, REV_RATES, SERVICE_NAMES  # noqa: F401

# ⚠️ ЮKassa переведена в спящий режим — бот по умолчанию работает через Альфа-Банк
# (см. services/alfabank.py и PAYMENT_PROVIDER). Модуль оставлен «про запас»:
# конфигурируем SDK только если ключи заданы, чтобы импорт был безопасным.
if SHOP_ID and SECRET_KEY:
    Configuration.account_id = SHOP_ID
    Configuration.secret_key = SECRET_KEY


async def create_payment(amount: int, chat_id, user_id) -> tuple:
    id_key = str(uuid.uuid4())
    payload = {
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
                "email": "mail.skillschool@gmail.com"
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

    }
    payment = await asyncio.to_thread(
        Payment.create,
        payload,
        id_key
    )
    logger.info(f"создали транзакцию для айди {user_id}")
    return payment.confirmation.confirmation_url, payment.id

