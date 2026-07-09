"""
Фасад выбора кассы. Один переключатель PAYMENT_PROVIDER решает, какая касса
активна, чтобы остальному коду (меню оплаты, main.py) было всё равно, кто именно
проводит платёж.

  "alfa"     — Альфа-Банк (по умолчанию, боевой режим).
  "yookassa" — ЮKassa (спящий режим, оставлена про запас).

Экспортирует единый интерфейс:
  create_payment(amount, chat_id, user_id[, source]) -> (pay_url, order_id)
  start_webhook_server(bot) -> aiohttp AppRunner
"""
from config.config_env import PAYMENT_PROVIDER
from config.utils import logger

if PAYMENT_PROVIDER == "yookassa":
    from services.payments import create_payment
    from services.yookassa_webhook import start_webhook_server
    logger.info("Касса: ЮKassa (спящий режим активирован вручную)")
else:
    from services.alfabank import create_payment
    from services.alfabank_webhook import start_webhook_server
    logger.info("Касса: Альфа-Банк")

__all__ = ["create_payment", "start_webhook_server"]
