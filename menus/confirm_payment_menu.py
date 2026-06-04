import asyncio
import socket

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
CHECK_INTERVAL = 8


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

    # 🔥 запускаем отдельный контроллер на каждый платеж
    asyncio.create_task(
        payment_monitor(
            payment_id=payment_id,
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
            sent_message=sent
        )
    )

    await callback.answer()


# ---------------------------
# PAYMENT MONITOR (1 платеж = 1 task)
# ---------------------------
async def payment_monitor(payment_id: str, chat_id: int, user_id: int, sent_message):

    start_time = asyncio.get_running_loop().time()

    while True:

        # ⛔ таймаут
        if asyncio.get_running_loop().time() - start_time > MAX_PAYMENT_LIFETIME:

            await bot.send_message(chat_id, "⌛ Время оплаты истекло. Создайте новый заказ.")

            try:
                await sent_message.delete()
            except Exception:
                pass

            logger.info(f"PAYMENT EXPIRED {payment_id}")
            return

        payment = await fetch_payment_safe(payment_id)

        if payment is None:
            await asyncio.sleep(CHECK_INTERVAL)
            continue

        status = getattr(payment, "status", None)

        # 🔄 ещё не оплатили
        if status == "pending":
            await asyncio.sleep(CHECK_INTERVAL)
            continue

        # ❌ отмена
        if status == "canceled":
            await bot.send_message(chat_id, "❌ Платеж отменен.")
            return

        # ✅ успех
        if status == "succeeded":

            amount = int(payment.amount.value)
            key = sheets.get_key(amount)

            sheets.add_used(
                REV_RATES[amount],
                user_id,
                key
            )

            await bot.send_message(
                chat_id,
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

            logger.info(f"PAYMENT SUCCESS {payment_id}")
            return

        await asyncio.sleep(CHECK_INTERVAL)


# ---------------------------
# SAFE FETCH (без флуда и блокировки)
# ---------------------------
async def fetch_payment_safe(payment_id: str):

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(Payment.find_one, payment_id),
            timeout=5
        )

    except asyncio.TimeoutError:
        logger.warning(f"Юкасса timeout {payment_id}")

    except (socket.gaierror, OSError) as e:
        logger.warning(f"Юкасса network error {e}")

    except Exception:
        logger.exception(f"Юкасса error {payment_id}")

    return None