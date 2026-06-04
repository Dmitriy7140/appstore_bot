import asyncio
import socket
import time

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router
from yookassa import Payment

from config.utils import logger
from main import bot
from services.payments import create_payment, RATES, REV_RATES
from repository.sheets.sheets import sheets
from services.sender_service import send_transaction_notice
ACTIVE_PAYMENTS = {}
rt = Router()

@rt.callback_query(lambda c: c.data.startswith("pay/"))
async def process_payment(callback: CallbackQuery):

    _, service, amount = callback.data.split("/")

    amount = int(amount)

    payment_url, payment_id = await create_payment(
        amount,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton(text="Прочти перед оплатой", callback_data="asfaq_payment")],
            [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")]
        ]
    )

    sent = await callback.message.answer(
        text=(
            f"К оплате {RATES[amount]} рублей\n\n"
            f"Ссылка для оплаты 👇\n\n"
            f"После оплаты дождитесь подтверждения ✅"
        ),
        reply_markup=keyboard
    )

    ACTIVE_PAYMENTS[payment_id] = {
        "created_at": time.time(),
        "callback": callback,
        "get_key": sheets.get_key,
        "sent_message": sent
    }
    await callback.answer()

# async def wait_payment(callback, get_key, payment_id, sent_message):
#     timeout = 11 * 60
#     resend_after = 30 * 60
#     start_time = asyncio.get_event_loop().time()
#     while True:
#         if asyncio.get_event_loop().time() - start_time > timeout:
#             await callback.message.answer("⌛ Время оплаты истекло")
#             await sent_message.delete()
#             logger.error(f"Время оплаты истекло у {callback.from_user.id}")
#             return
#         payment = await fetch_payment_safe(payment_id)
#         if payment is None:
#             await asyncio.sleep(5)
#             continue
#
#         if payment.status == "succeeded":
#             key = get_key(int(payment.amount.value))
#
#             await callback.message.answer("✅ Оплата прошла! Вот ваш ключ:\n\n"
#                                           f"<code>{key}</code>", parse_mode="HTML",
#                                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
#                                               [InlineKeyboardButton(text="Как активировать код?",
#                                                                     callback_data="asfaq_code")],
#                                               [InlineKeyboardButton(
#                                                   text="Как поменять регион?",
#
#                                                   callback_data="asfaq_region")]]))
#             user_id = int(payment.metadata["user_id"])
#             sheets.add_used(REV_RATES[int(payment.amount.value)], user_id, key)
#
#             logger.info(f"Отправляем транзакцию для айди {user_id}")
#             await send_transaction_notice(
#                 bot,
#                 telegram_id=user_id,
#                 tx_id=payment.id,
#                 amount=int(payment.amount.value),
#                 code=key
#             )
#             logger.info(f"Оплата подтверждена! user_id:{user_id}, amount:{payment.amount.value}")
#             break
#         elif payment.status == "canceled":
#             await callback.message.answer(
#                 "❌Платеж отменен. Попробуйте еще раз или свяжитесь с менеджером @MANAGER_2PAY")
#             logger.error(f"Оплата была отменена! user_id:{callback.from_user.id}")
#             break
#         await asyncio.sleep(5)
async def handle_payment(payment, data):
    callback = data["callback"]
    get_key = data["get_key"]
    sent_message = data["sent_message"]

    if payment.status == "succeeded":

        key = get_key(int(payment.amount.value))
        user_id = int(payment.metadata["user_id"])

        await callback.message.answer(
            f"✅ Оплата прошла!\n\n<code>{key}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Как активировать код?", callback_data="asfaq_code")],
                [InlineKeyboardButton(text="Как поменять регион?", callback_data="asfaq_region")]
            ])
        )

        sheets.add_used(
            REV_RATES[int(payment.amount.value)],
            user_id,
            key
        )

        await send_transaction_notice(
            bot,
            telegram_id=user_id,
            tx_id=payment.id,
            amount=int(payment.amount.value),
            code=key
        )

    elif payment.status == "canceled":

        await callback.message.answer(
            "❌ Платеж отменен. Попробуйте еще раз или свяжитесь с менеджером @MANAGER_2PAY"
        )
async def fetch_payment_safe(payment_id: str):
    for attempt in range(3):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(Payment.find_one, payment_id),
                timeout=5
            )

        except asyncio.TimeoutError:
            logger.warning(f"Ждем статус транзакции для {payment_id}")

        except (socket.gaierror, OSError) as e:
            logger.warning(f"Сетевая ошибка Юкассы (попытка {attempt}): {e}")

        except Exception as e:
            logger.warning(f"Неизвестная ошибка Юкассы (попытка {attempt}): {e}")

        await asyncio.sleep(2 * (attempt + 1))  # backoff

    return None
async def payment_worker():
    while True:
        now = time.time()
        if not ACTIVE_PAYMENTS:
            await asyncio.sleep(3)
            continue

        for payment_id in list(ACTIVE_PAYMENTS.keys()):
            data = ACTIVE_PAYMENTS[payment_id]
            if now - data["created_at"] > 590:

                try:
                    await asyncio.to_thread(
                        Payment.cancel,
                        payment_id
                    )
                except Exception as e:
                    logger.warning(f"Не удалось отменить платеж {payment_id}: {e}")

                try:
                    await data["callback"].message.answer(
                        "⌛ Время оплаты истекло. Ссылка на оплату больше недействительна."
                    )
                except Exception:
                    logger.exception("Не удалось уведомить пользователя")

                ACTIVE_PAYMENTS.pop(payment_id, None)
                continue

            payment = await fetch_payment_safe(payment_id)

            if payment is None:
                continue

            if payment.status in ("succeeded", "canceled"):
                try:
                    await handle_payment(payment, data)
                except Exception as e:
                    logger.exception(f"Ошибка обработки платежа {payment_id}: {e}")
                finally:
                    ACTIVE_PAYMENTS.pop(payment_id, None)
        await asyncio.sleep(5)