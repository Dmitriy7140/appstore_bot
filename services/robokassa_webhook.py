"""
HTTP-эндпоинт ResultURL для Robokassa.

После оплаты Robokassa шлёт на ResultURL запрос (GET или POST — настраивается в ЛК)
с параметрами OutSum, InvId, SignatureValue и нашими Shp_*. Подпись проверяется
Паролем#2. В ответ ОБЯЗАТЕЛЬНО отдаём тело `OK{InvId}` — иначе Robokassa повторяет
уведомление.

Контекст заказа (кому выдать ключ) берём из robokassa_orders по InvId; сумму сверяем
с OutSum. Идемпотентность выдачи — processed_payments (claim_payment по InvId).
"""
from decimal import Decimal, InvalidOperation

from aiohttp import web
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.utils import logger
from config.config_env import (
    WEBHOOK_HOST, WEBHOOK_PORT, ROBOKASSA_RESULT_PATH, ROBOKASSA_PASSWORD2,
    ADMIN_CHAT_ID,
)
from repository.sheets.sheets import sheets, run_sheet
from services.sender_service import send_transaction_notice
from services.tg_retry import send_flood_safe
from services.robokassa import hash_signature, shp_suffix
from repository.database.database import (
    claim_payment, release_payment, get_robokassa_order,
)


async def _alert_admin(bot, text: str):
    try:
        await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="HTML")
    except Exception:
        logger.exception("Не смог отправить алерт админу")


def _verify_signature(out_sum: str, inv_id: str, shp: dict, received: str) -> bool:
    """hash(OutSum:InvId:Пароль#2[:Shp_* по алфавиту]) == SignatureValue (регистр не важен)."""
    if not received:
        return False
    expected = hash_signature(f"{out_sum}:{inv_id}:{ROBOKASSA_PASSWORD2}" + shp_suffix(shp))
    return expected.lower() == received.strip().lower()


async def _dispense_key(bot, order: dict, inv_id: int) -> bool:
    """Выдать ключ (идемпотентно). True — обработано/уже обработано, False — временный сбой."""
    user_id = order["user_id"]
    chat_id = order["chat_id"]
    nominal = order["nominal"]              # номинал в лирах (лист 'used')
    amount_rub = order["amount_rub"]        # рубли — ключ листа с кодами

    claim_key = f"robokassa:{inv_id}"
    if not await claim_payment(claim_key):
        logger.info(f"Robokassa: InvId={inv_id} уже обработан — пропускаем")
        return True

    # --- 1. Извлекаем ключ. Это расходует инвентарь — точка невозврата. ---
    try:
        key = await run_sheet(sheets.get_key, amount_rub)
    except Exception as e:
        logger.exception(f"Robokassa InvId={inv_id}: ошибка получения ключа: {e}")
        await release_payment(claim_key)        # ключ не тронут — ретрай безопасен
        return False

    if not key:
        logger.error(f"Robokassa: нет ключей номинала {nominal} для InvId={inv_id}")
        await release_payment(claim_key)
        await _alert_admin(
            bot,
            f"🚨 Нет ключей номинала {nominal} лир!\n"
            f"Robokassa InvId <code>{inv_id}</code>, юзер {user_id}"
        )
        return False

    # --- 2. Ключ извлечён. claim НЕ отпускаем (иначе двойная выдача). ---
    try:
        await run_sheet(sheets.add_used, nominal, user_id, key)
        await send_flood_safe(lambda: bot.send_message(
            chat_id,
            f"✅ Оплата прошла!\n\n<code>{key}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Как активировать код?", callback_data="asfaq_code")],
                [InlineKeyboardButton(text="Как поменять регион?", callback_data="asfaq_region")],
            ]),
        ))
        await send_transaction_notice(
            bot,
            telegram_id=user_id,
            tx_id=f"robokassa-{inv_id}",
            amount=amount_rub,
            code=key,
            source=order.get("source"),
        )
        logger.info(f"Robokassa: InvId={inv_id} обработан, ключ выдан юзеру {user_id}")
    except Exception as e:
        logger.exception(f"Robokassa InvId={inv_id}: ключ извлечён, но доставка упала: {e}")
        await _alert_admin(
            bot,
            f"🚨 Robokassa InvId <code>{inv_id}</code>: ключ <code>{key}</code> извлечён, "
            f"но НЕ доставлен юзеру {user_id} (chat {chat_id}). Надо выдать вручную!"
        )
    return True


async def _handle(request: web.Request) -> web.Response:
    bot = request.app["bot"]

    if request.method == "POST":
        data = dict(await request.post())
    else:
        data = dict(request.query)

    # ВРЕМЕННО (диагностика чеков): полный дамп того, что реально прислала Robokassa.
    # Убрать после отладки — тут может быть email покупателя.
    logger.info(f"Robokassa ResultURL RAW [{request.method}]: {dict(data)}")

    out_sum = data.get("OutSum") or data.get("OutSumm") or ""
    inv_id_raw = data.get("InvId") or ""
    signature = data.get("SignatureValue", "")
    shp = {k: v for k, v in data.items() if k.lower().startswith("shp_")}

    logger.info(f"Robokassa ResultURL: InvId={inv_id_raw}, OutSum={out_sum}")

    if not _verify_signature(out_sum, inv_id_raw, shp, signature):
        logger.warning(f"Robokassa: неверная подпись ResultURL, InvId={inv_id_raw}")
        return web.Response(status=400, text="bad sign")

    try:
        inv_id = int(inv_id_raw)
    except ValueError:
        return web.Response(status=400, text="bad InvId")

    order = await get_robokassa_order(inv_id)
    if not order:
        # подпись валидна, но заказа нет — квитируем, чтобы Robokassa не долбила ретраями
        logger.error(f"Robokassa: заказ InvId={inv_id} не найден в БД")
        return web.Response(text=f"OK{inv_id}")

    # сверяем сумму (подпись уже подтвердила подлинность)
    try:
        if Decimal(out_sum) != Decimal(order["amount_rub"]):
            logger.error(
                f"Robokassa InvId={inv_id}: сумма не сошлась "
                f"(оплачено {out_sum}, ожидали {order['amount_rub']})"
            )
            await _alert_admin(
                bot,
                f"⚠️ Robokassa InvId <code>{inv_id}</code>: сумма {out_sum}₽ "
                f"≠ ожидаемой {order['amount_rub']}₽. Ключ НЕ выдан."
            )
            return web.Response(text=f"OK{inv_id}")
    except (InvalidOperation, TypeError):
        return web.Response(status=400, text="bad OutSum")

    ok = await _dispense_key(bot, order, inv_id)
    if not ok:
        # временный сбой (нет ключей / Sheets упал) — просим Robokassa повторить
        return web.Response(status=500, text="retry later")

    return web.Response(text=f"OK{inv_id}")


async def _healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    # Robokassa может слать ResultURL как GET, так и POST — принимаем оба.
    app.router.add_get(ROBOKASSA_RESULT_PATH, _handle)
    app.router.add_post(ROBOKASSA_RESULT_PATH, _handle)
    app.router.add_get("/healthz", _healthz)
    return app


async def start_webhook_server(bot) -> web.AppRunner:
    """Поднимает aiohttp-сервер для ResultURL Robokassa и возвращает runner."""
    runner = web.AppRunner(build_app(bot), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    logger.info(f"Robokassa ResultURL слушает http://{WEBHOOK_HOST}:{WEBHOOK_PORT}{ROBOKASSA_RESULT_PATH}")
    return runner
