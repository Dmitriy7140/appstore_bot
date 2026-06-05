"""
HTTP-эндпоинт для уведомлений ЮKassa (HTTP-notifications / webhooks).

Заменяет поллинг статуса оплаты: ЮKassa сама присылает POST на `payment.succeeded`
и повторяет уведомление, пока не получит 200. Контекст (кому выдать ключ) берём из
metadata платежа — она проставляется в services/payments.create_payment.

Выдача защищена от двойного срабатывания через таблицу processed_payments
(см. repository/database/database.claim_payment).
"""
import asyncio
from decimal import Decimal, InvalidOperation
from ipaddress import ip_address, ip_network

from aiohttp import web
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.utils import logger
from config.config_env import (
    WEBHOOK_HOST, WEBHOOK_PORT, WEBHOOK_PATH,
    YOOKASSA_ALLOWED_IPS, ADMIN_CHAT_ID,
)
from repository.sheets.sheets import sheets
from services.payments import REV_RATES
from services.sender_service import send_transaction_notice
from repository.database.database import claim_payment, release_payment


# Официальные подсети, с которых ЮKassa шлёт уведомления.
# https://yookassa.ru/developers/using-api/webhooks#ip
_DEFAULT_YOOKASSA_NETS = [
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11/32",
    "77.75.156.35/32",
    "77.75.154.128/25",
    "2a02:5180::/32",
]


def _build_networks():
    raw = [s.strip() for s in YOOKASSA_ALLOWED_IPS.split(",") if s.strip()]
    raw = raw or _DEFAULT_YOOKASSA_NETS
    nets = []
    for cidr in raw:
        try:
            nets.append(ip_network(cidr, strict=False))
        except ValueError:
            logger.warning(f"Битый CIDR в YOOKASSA_ALLOWED_IPS: {cidr}")
    return nets


_ALLOWED_NETS = _build_networks()


def _client_ip(request: web.Request) -> str:
    # за nginx настоящий адрес приходит в X-Forwarded-For (берём первый)
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote or ""


def _ip_allowed(ip: str) -> bool:
    try:
        addr = ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _ALLOWED_NETS)


async def _alert_admin(bot, text: str):
    try:
        await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="HTML")
    except Exception:
        logger.exception("Не смог отправить алерт админу")


async def _handle(request: web.Request) -> web.Response:
    bot = request.app["bot"]

    ip = _client_ip(request)
    if not _ip_allowed(ip):
        logger.warning(f"Webhook с недоверенного IP: {ip!r}")
        return web.Response(status=403)

    try:
        data = await request.json()
    except Exception:
        logger.warning("Webhook: тело запроса не JSON")
        return web.Response(status=400)

    event = data.get("event")
    obj = data.get("object") or {}
    payment_id = obj.get("id")

    if not payment_id:
        return web.Response(status=400)

    # реагируем только на успешную оплату; canceled/waiting/refund просто квитируем
    if event != "payment.succeeded":
        return web.Response(status=200)

    meta = obj.get("metadata") or {}
    try:
        user_id = int(meta["user_id"])
        chat_id = int(meta.get("chat_id", user_id))
        amount_rub = int(Decimal(str(obj["amount"]["value"])))
    except (KeyError, ValueError, TypeError, InvalidOperation) as e:
        # битые данные не имеет смысла ретраить бесконечно — квитируем и алертим
        logger.exception(f"Webhook: не разобрал платёж {payment_id}: {e}")
        await _alert_admin(bot, f"⚠️ Не разобрал webhook платежа <code>{payment_id}</code>")
        return web.Response(status=200)

    if amount_rub not in REV_RATES:
        logger.error(f"Неизвестный номинал {amount_rub} в платеже {payment_id}")
        await _alert_admin(bot, f"⚠️ Неизвестный номинал {amount_rub}₽, платёж <code>{payment_id}</code>")
        return web.Response(status=200)

    # идемпотентность: атомарно столбим платёж до любой выдачи
    if not await claim_payment(payment_id):
        logger.info(f"Платёж {payment_id} уже обработан — пропускаем")
        return web.Response(status=200)

    # --- 1. Извлекаем ключ. Это расходует инвентарь — точка невозврата. ---
    try:
        key = await asyncio.to_thread(sheets.get_key, amount_rub)
    except Exception as e:
        logger.exception(f"Платёж {payment_id}: ошибка получения ключа: {e}")
        await release_payment(payment_id)          # ключ не тронут — ретрай безопасен
        return web.Response(status=500)

    if not key:
        logger.error(f"Нет ключей номинала {amount_rub} для платежа {payment_id}")
        await release_payment(payment_id)           # вдруг пополнят — пусть ЮKassa повторит
        await _alert_admin(
            bot,
            f"🚨 Нет ключей номинала {REV_RATES[amount_rub]} лир!\n"
            f"Платёж <code>{payment_id}</code>, юзер {user_id}"
        )
        return web.Response(status=500)

    # --- 2. Ключ извлечён. Дальше claim НЕ отпускаем (иначе двойная выдача). ---
    try:
        await asyncio.to_thread(sheets.add_used, REV_RATES[amount_rub], user_id, key)

        await bot.send_message(
            chat_id,
            f"✅ Оплата прошла!\n\n<code>{key}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Как активировать код?", callback_data="asfaq_code")],
                [InlineKeyboardButton(text="Как поменять регион?", callback_data="asfaq_region")],
            ]),
        )

        await send_transaction_notice(
            bot,
            telegram_id=user_id,
            tx_id=payment_id,
            amount=amount_rub,
            code=key,
        )
        logger.info(f"Платёж {payment_id} обработан, ключ выдан юзеру {user_id}")
    except Exception as e:
        # ключ уже извлечён из таблицы — отпускать claim нельзя, иначе выдадим второй.
        # Зовём админа доставить вручную.
        logger.exception(f"Платёж {payment_id}: ключ извлечён, но доставка упала: {e}")
        await _alert_admin(
            bot,
            f"🚨 Платёж <code>{payment_id}</code>: ключ <code>{key}</code> извлечён, "
            f"но НЕ доставлен юзеру {user_id} (chat {chat_id}). Надо выдать вручную!"
        )

    return web.Response(status=200)


async def _healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(WEBHOOK_PATH, _handle)
    app.router.add_get("/healthz", _healthz)
    return app


async def start_webhook_server(bot) -> web.AppRunner:
    """Поднимает aiohttp-сервер для уведомлений ЮKassa и возвращает runner."""
    # access_log=None — глушим «сырой» лог запросов (сканеры интернета флудят 404);
    # осмысленные события (выдача ключа, недоверенный IP) логируются в _handle.
    runner = web.AppRunner(build_app(bot), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    logger.info(f"ЮKassa webhook слушает http://{WEBHOOK_HOST}:{WEBHOOK_PORT}{WEBHOOK_PATH}")
    return runner
