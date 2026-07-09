"""
HTTP-эндпоинт для callback-уведомлений Альфа-Банка.

В отличие от ЮKassa (JSON POST) Альфа шлёт callback ОБЫЧНЫМ GET-запросом:
  {url}?mdOrder=..&orderNumber=..&checksum=..&operation=deposited&status=1&callbackCreationDate=..

operation: approved (холд, 2-стадийная), deposited (оплата завершена),
           reversed (отмена), refunded (возврат), bindingCreated/…, declinedByTimeout, …
status:    1 — успех, 0 — ошибка.

Callback НЕ несёт наши метаданные (кому выдать ключ) — только orderNumber/mdOrder.
Контекст берём из таблицы alfa_orders (её заполняет services/alfabank.create_payment),
а факт и сумму оплаты ПЕРЕПРОВЕРЯЕМ серверным запросом getOrderStatusExtended.do —
это надёжнее контрольной суммы (подделать нельзя, спрашиваем банк напрямую).

Идемпотентность выдачи — через processed_payments (claim_payment по mdOrder).
Шлюз повторяет уведомление, пока не получит 200 OK.
"""
import hmac
import hashlib

from aiohttp import web
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.utils import logger
from config.config_env import (
    WEBHOOK_HOST, WEBHOOK_PORT, ALFA_WEBHOOK_PATH,
    ALFA_CALLBACK_TOKEN, ADMIN_CHAT_ID,
)
from repository.sheets.sheets import sheets, run_sheet
from services.sender_service import send_transaction_notice
from services.tg_retry import send_flood_safe
from services.alfabank import get_order_status
from repository.database.database import (
    claim_payment, release_payment,
    get_alfa_order, attach_alfa_md_order,
)


# Статус заказа в шлюзе, при котором ключ можно выдавать (одностадийная оплата).
_ORDER_STATUS_DEPOSITED = 2


async def _alert_admin(bot, text: str):
    try:
        await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="HTML")
    except Exception:
        logger.exception("Не смог отправить алерт админу")


def _verify_checksum(params: dict, token: str) -> bool:
    """
    Симметричная проверка подписи (HMAC-SHA256) по алгоритму Альфы:
      1. убрать checksum и sign_alias;
      2. отсортировать пары по имени параметра по возрастанию;
      3. склеить в строку 'name;value;name;value;...';
      4. HMAC-SHA256(строка, callback_token) в ВЕРХНЕМ регистре;
      5. сравнить с checksum из уведомления.
    """
    received = params.get("checksum")
    if not received:
        return False
    filtered = {
        k: v for k, v in params.items()
        if k not in ("checksum", "sign_alias")
    }
    data = "".join(f"{k};{filtered[k]};" for k in sorted(filtered))
    expected = hmac.new(
        token.encode("utf-8"), data.encode("utf-8"), hashlib.sha256
    ).hexdigest().upper()
    return hmac.compare_digest(expected, received.upper())


async def _dispense_key(bot, order: dict, md_order: str) -> web.Response:
    """
    Общая для ЮKassa/Альфы часть: атомарно столбим платёж, тянем ключ из таблицы,
    выдаём покупателю и уведомляем админа. Возвращает HTTP-ответ для шлюза.
    """
    user_id = order["user_id"]
    chat_id = order["chat_id"]
    nominal = order["nominal"]                       # номинал в лирах (для листа 'used')
    amount_rub = order["amount_kopecks"] // 100       # сумма в рублях — ключ листа с кодами

    # идемпотентность: атомарно столбим платёж (ключ mdOrder) до любой выдачи
    if not await claim_payment(md_order):
        logger.info(f"Альфа: платёж {md_order} уже обработан — пропускаем")
        return web.Response(status=200)

    # --- 1. Извлекаем ключ. Это расходует инвентарь — точка невозврата. ---
    # sheets.get_key берёт лист по РУБЛЁВОЙ сумме (ALL_SHEETS: 400->"100" и т.д.),
    # а sheets.add_used пишет ЛИРОВЫЙ номинал — как и в вебхуке ЮKassa.
    try:
        key = await run_sheet(sheets.get_key, amount_rub)
    except Exception as e:
        logger.exception(f"Альфа {md_order}: ошибка получения ключа: {e}")
        await release_payment(md_order)          # ключ не тронут — ретрай безопасен
        return web.Response(status=500)

    if not key:
        logger.error(f"Альфа: нет ключей номинала {nominal} для платежа {md_order}")
        await release_payment(md_order)           # вдруг пополнят — пусть шлюз повторит
        await _alert_admin(
            bot,
            f"🚨 Нет ключей номинала {nominal} лир!\n"
            f"Платёж <code>{md_order}</code>, юзер {user_id}"
        )
        return web.Response(status=500)

    # --- 2. Ключ извлечён. Дальше claim НЕ отпускаем (иначе двойная выдача). ---
    try:
        await run_sheet(sheets.add_used, nominal, user_id, key)

        # flood-safe: во время массовой рассылки лимит бота исчерпан и обычный
        # send_message упал бы с 429 → покупатель остался бы без кода. Ждём и повторяем.
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
            tx_id=md_order,
            amount=amount_rub,
            code=key,
            source=order.get("source"),
        )
        logger.info(f"Альфа: платёж {md_order} обработан, ключ выдан юзеру {user_id}")
    except Exception as e:
        # ключ уже извлечён — отпускать claim нельзя, иначе выдадим второй.
        logger.exception(f"Альфа {md_order}: ключ извлечён, но доставка упала: {e}")
        await _alert_admin(
            bot,
            f"🚨 Платёж <code>{md_order}</code>: ключ <code>{key}</code> извлечён, "
            f"но НЕ доставлен юзеру {user_id} (chat {chat_id}). Надо выдать вручную!"
        )

    return web.Response(status=200)


async def _handle(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    params = dict(request.query)

    order_number = params.get("orderNumber")
    md_order = params.get("mdOrder")
    operation = params.get("operation")
    status = params.get("status")

    logger.info(
        f"Альфа callback: operation={operation}, status={status}, "
        f"orderNumber={order_number}, mdOrder={md_order}"
    )

    # Уведомления о связках (без orderNumber) нам не нужны — просто квитируем.
    if not order_number:
        return web.Response(status=200)

    # Проверка подписи (если задан callback-токен) — МЯГКАЯ: при несовпадении
    # не отклоняем сразу, а логируем и полагаемся на серверную перепроверку ниже
    # (getOrderStatusExtended авторитетна — статус оплаты спрашиваем у банка напрямую).
    # Причина: в документации Альфы неоднозначно, входит ли callbackCreationDate в
    # набор для контрольной суммы, поэтому жёсткий 403 рискует потерять реальные оплаты.
    if ALFA_CALLBACK_TOKEN and not _verify_checksum(params, ALFA_CALLBACK_TOKEN):
        logger.warning(
            f"Альфа callback: checksum не сошлась (orderNumber={order_number}) — "
            f"продолжаем через getOrderStatusExtended"
        )

    # Реагируем только на успешное завершение оплаты (одностадийная = deposited).
    # approved (холд) без deposited для нашей схемы не финальный; прочее — квитируем.
    if operation != "deposited" or status != "1":
        logger.info(f"Альфа callback: пропускаем operation={operation}/status={status}")
        return web.Response(status=200)

    order = await get_alfa_order(order_number)
    if not order:
        # не наш заказ (например, сайтовая оплата на том же мерчанте) — квитируем
        logger.warning(f"Альфа callback: заказ {order_number} не найден в БД")
        return web.Response(status=200)

    if md_order and not order.get("md_order"):
        await attach_alfa_md_order(order_number, md_order)

    # --- Серверная перепроверка: спрашиваем банк напрямую, реально ли оплачено. ---
    try:
        st = await get_order_status(order_id=md_order, order_number=order_number)
    except Exception as e:
        logger.exception(f"Альфа {order_number}: getOrderStatusExtended упал: {e}")
        return web.Response(status=500)          # пусть шлюз повторит уведомление

    order_status = st.get("orderStatus")
    paid_amount = st.get("amount")
    if order_status != _ORDER_STATUS_DEPOSITED:
        logger.warning(
            f"Альфа {order_number}: callback deposited, но orderStatus={order_status} "
            f"(actionCode={st.get('actionCode')}) — ключ не выдаём"
        )
        return web.Response(status=200)

    # сверяем сумму: защищает от несоответствия номинала
    if paid_amount is not None and int(paid_amount) != int(order["amount_kopecks"]):
        logger.error(
            f"Альфа {order_number}: сумма не сошлась "
            f"(оплачено {paid_amount}, ожидали {order['amount_kopecks']})"
        )
        await _alert_admin(
            bot,
            f"⚠️ Платёж <code>{md_order}</code>: сумма {paid_amount} коп. "
            f"≠ ожидаемой {order['amount_kopecks']} коп. Ключ НЕ выдан."
        )
        return web.Response(status=200)

    # идентификатор для идемпотентности — mdOrder (или orderNumber как запасной)
    return await _dispense_key(bot, order, md_order or order_number)


async def _healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    # callback приходит GET-запросом
    app.router.add_get(ALFA_WEBHOOK_PATH, _handle)
    app.router.add_get("/healthz", _healthz)
    return app


async def start_webhook_server(bot) -> web.AppRunner:
    """Поднимает aiohttp-сервер для callback-уведомлений Альфы и возвращает runner."""
    runner = web.AppRunner(build_app(bot), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    logger.info(f"Альфа callback слушает http://{WEBHOOK_HOST}:{WEBHOOK_PORT}{ALFA_WEBHOOK_PATH}")
    return runner
