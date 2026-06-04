import asyncio
import time
from decimal import Decimal

from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from yookassa import Payment

from config.utils import logger
from main import bot
from repository.sheets.sheets import sheets
from services.payments import create_payment, RATES, REV_RATES
from services.sender_service import send_transaction_notice

rt = Router()

MAX_PAYMENT_LIFETIME = 600
CHECK_INTERVAL = 5

ACTIVE_PAYMENTS = {}


# -------------------------
# CALLBACK
# -------------------------
@rt.callback_query(lambda c: c.data.startswith("pay/"))
async def process_payment(callback: CallbackQuery):

    _, service, amount = callback.data.split("/")
    amount = int(amount)

    payment_url, payment_id = await create_payment(
        amount,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="Прочти перед оплатой", callback_data="asfaq_payment")],
        [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")]
    ])

    sent = await callback.message.answer(
        f"К оплате {RATES[amount]} рублей\n\n"
        f"Ссылка для оплаты 👇\n\n"
        f"После оплаты дождитесь подтверждения ✅",
        reply_markup=keyboard
    )

    ACTIVE_PAYMENTS[payment_id] = {
        "created_at": time.time(),
        "chat_id": callback.message.chat.id,
        "user_id": callback.from_user.id,
        "message": sent
    }

    await callback.answer()


# -------------------------
# WORKER
# -------------------------
async def payment_worker():
    while True:
        now = time.time()

        for payment_id in list(ACTIVE_PAYMENTS.keys()):
            data = ACTIVE_PAYMENTS.get(payment_id)
            if not data:
                continue

            # timeout
            if now - data["created_at"] > MAX_PAYMENT_LIFETIME:
                try:
                    await bot.send_message(
                        data["chat_id"],
                        "⌛ Время оплаты истекло. Создайте новый заказ."
                    )
                except Exception:
                    logger.exception("Timeout message send failed")

                ACTIVE_PAYMENTS.pop(payment_id, None)
                continue

            payment = await fetch_payment_safe(payment_id)
            if not payment:
                continue

            status = payment.status

            # pending — ничего не делаем
            if status == "pending":
                continue

            # canceled
            if status == "canceled":
                try:
                    await bot.send_message(
                        data["chat_id"],
                        "❌ Платеж отменен."
                    )
                except Exception:
                    logger.exception("Cancel message failed")

                ACTIVE_PAYMENTS.pop(payment_id, None)
                continue

            # succeeded
            if status == "succeeded":

                try:
                    amount = int(Decimal(payment.amount.value))  # 🔥 безопасно

                    user_id = data["user_id"]

                    # защита от неправильной суммы
                    if amount not in REV_RATES:
                        logger.error(f"Unknown payment amount: {amount}")
                        ACTIVE_PAYMENTS.pop(payment_id, None)
                        continue

                    key = sheets.get_key(amount)

                    sheets.add_used(
                        REV_RATES[amount],
                        user_id,
                        key
                    )

                    await bot.send_message(
                        data["chat_id"],
                        f"✅ Оплата прошла!\n\n<code>{key}</code>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="Как активировать код?", callback_data="asfaq_code")],
                            [InlineKeyboardButton(text="Как поменять регион?", callback_data="asfaq_region")]
                        ])
                    )

                    await send_transaction_notice(
                        bot,
                        telegram_id=user_id,
                        tx_id=payment.id,
                        amount=amount,
                        code=key
                    )

                except Exception as e:
                    logger.exception(f"Payment processing error: {e}")

                finally:
                    ACTIVE_PAYMENTS.pop(payment_id, None)

        await asyncio.sleep(CHECK_INTERVAL)


# -------------------------
# SAFE FETCH
# -------------------------
async def fetch_payment_safe(payment_id: str):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(Payment.find_one, payment_id),
            timeout=5
        )
    except Exception:
        logger.warning(f"Payment fetch error {payment_id}")
        return None