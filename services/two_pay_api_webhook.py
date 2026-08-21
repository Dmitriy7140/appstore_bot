"""Authenticated events from the 2PAY API.

The API owns payment confirmation and inventory. This process owns every
Telegram Bot API call, including payment-code delivery. A successful response
means the buyer message was accepted by Telegram or was already delivered.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import time
from dataclasses import asdict, dataclass
from uuid import UUID

from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.config_env import (
    API_DELIVERY_LEASE_SECONDS,
    TWO_PAY_API_WEBHOOK_HOST,
    TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS,
    TWO_PAY_API_WEBHOOK_PATH,
    TWO_PAY_API_WEBHOOK_PORT,
    TWO_PAY_API_WEBHOOK_TOKEN,
)
from config.utils import logger
from repository.sqlite_storage import (
    DeliveryPayloadConflictError,
    SQLiteRepository,
)
from services.tg_retry import send_flood_safe


BOT_APP_KEY: web.AppKey[Bot] = web.AppKey("bot", Bot)
STORAGE_APP_KEY: web.AppKey[SQLiteRepository] = web.AppKey(
    "sqlite_repository", SQLiteRepository
)


class WebhookInputError(ValueError):
    """The authenticated caller sent an invalid event body."""


class DeliveryInProgressError(RuntimeError):
    """Another request currently owns the local delivery lease."""


@dataclass(frozen=True, slots=True)
class PaymentCodeEvent:
    transaction_id: str
    recipient_telegram_id: int
    code: str
    region: str
    nominal: int
    amount_rub: int


@dataclass(frozen=True, slots=True)
class ReferralRewardEvent:
    reward_id: UUID
    recipient_telegram_id: int
    referred_telegram_id: int | None
    key: str
    transaction_id: str


async def _handle(request: web.Request) -> web.Response:
    raw_body = await request.read()
    if not _is_authenticated(request, raw_body):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        body = json.loads(raw_body.decode("utf-8"))
        if not isinstance(body, dict):
            raise WebhookInputError("Body must be an object")
        header_event = request.headers.get("X-2PAY-Event")
        if header_event:
            event = header_event
            payload = body
        else:
            event = body.get("event")
            payload = body.get("payload")
            if not isinstance(event, str) or not isinstance(payload, dict):
                raise WebhookInputError("event and payload are required")
        bot = request.app[BOT_APP_KEY]
        repository = request.app[STORAGE_APP_KEY]
        if event == "payment.code.v1":
            result = await _deliver_payment_once(bot, repository, _payment_event(payload))
        elif event == "telegram.test.v1":
            await _send_test(bot, _positive_int(payload.get("recipient_telegram_id"), "recipient_telegram_id"))
            result = {"delivered": True}
        elif event == "telegram.html.v1":
            await _send_html(bot, payload)
            result = {"delivered": True}
        elif event == "referral_activated":
            result = await _deliver_referral_reward_once(
                bot, repository, _referral_reward_event(payload)
            )
        else:
            raise WebhookInputError("Unsupported event")
    except (UnicodeDecodeError, json.JSONDecodeError, WebhookInputError) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except DeliveryPayloadConflictError as error:
        logger.error("Conflicting 2PAY delivery event: %s", error)
        return web.json_response({"ok": False, "error": "delivery_id_conflict"}, status=409)
    except DeliveryInProgressError:
        # Ask the API outbox to retry after the short local lease expires.
        return web.json_response({"ok": False, "error": "delivery_in_progress"}, status=503)
    except TelegramForbiddenError:
        # A user who has blocked the bot cannot receive a code. Returning 503
        # preserves the paid event for retry after the user unblocks/starts it.
        logger.warning("Telegram refused a 2PAY payment delivery")
        return web.json_response({"ok": False, "error": "telegram_forbidden"}, status=503)
    except Exception:
        logger.exception("2PAY webhook delivery failed")
        return web.json_response({"ok": False, "error": "delivery_failed"}, status=503)
    return web.json_response({"ok": True, **result})


def _is_authenticated(request: web.Request, raw_body: bytes) -> bool:
    token = TWO_PAY_API_WEBHOOK_TOKEN
    if not token:
        logger.error("TWO_PAY_API_WEBHOOK_TOKEN is not configured")
        return False
    timestamp = request.headers.get("X-2PAY-Timestamp", "")
    signature = request.headers.get("X-2PAY-Signature", "")
    if not timestamp.isdecimal() or not signature.startswith("sha256="):
        return False
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return False
    if age > TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS:
        return False
    expected = hmac.new(
        token.encode("utf-8"),
        timestamp.encode("ascii") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def _payment_event(payload: dict[str, object]) -> PaymentCodeEvent:
    transaction_id = payload.get("transaction_id")
    code = payload.get("code")
    region = payload.get("region")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise WebhookInputError("transaction_id is required")
    if not isinstance(code, str) or not code:
        raise WebhookInputError("code is required")
    if not isinstance(region, str) or not region:
        raise WebhookInputError("region is required")
    return PaymentCodeEvent(
        transaction_id=transaction_id,
        recipient_telegram_id=_positive_int(
            payload.get("recipient_telegram_id"), "recipient_telegram_id"
        ),
        code=code,
        region=region,
        nominal=_positive_int(payload.get("nominal"), "nominal"),
        amount_rub=_positive_int(payload.get("amount_rub"), "amount_rub"),
    )


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise WebhookInputError(f"{name} must be a positive integer")
    return value


def _referral_reward_event(payload: dict[str, object]) -> ReferralRewardEvent:
    reward_id_value = payload.get("reward_id")
    key = payload.get("key")
    transaction_id = payload.get("transaction_id")
    if not isinstance(reward_id_value, str):
        raise WebhookInputError("reward_id is required")
    try:
        reward_id = UUID(reward_id_value)
    except ValueError as error:
        raise WebhookInputError("reward_id must be a UUID") from error
    if not isinstance(key, str) or not key:
        raise WebhookInputError("key is required")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise WebhookInputError("transaction_id is required")
    referred = payload.get("referred_telegram_id")
    if referred is not None:
        referred = _positive_int(referred, "referred_telegram_id")
    return ReferralRewardEvent(
        reward_id=reward_id,
        recipient_telegram_id=_positive_int(
            payload.get("recipient_telegram_id"), "recipient_telegram_id"
        ),
        referred_telegram_id=referred,
        key=key,
        transaction_id=transaction_id,
    )


def _payload_hash(event: PaymentCodeEvent | ReferralRewardEvent) -> str:
    payload = json.dumps(
        asdict(event),
        default=str,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _message_id(message: object) -> int | None:
    value = getattr(message, "message_id", None)
    return value if isinstance(value, int) else None


async def _deliver_payment_once(
    bot: Bot, repository: SQLiteRepository, event: PaymentCodeEvent
) -> dict[str, bool]:
    payload_hash = _payload_hash(event)
    claim = await repository.claim_payment_delivery(
        event.transaction_id,
        payload_hash,
        API_DELIVERY_LEASE_SECONDS,
    )
    if claim == "already_delivered":
        return {"delivered": True, "already_delivered": True}
    if claim == "in_progress":
        raise DeliveryInProgressError
    try:
        message_id = await _deliver_payment_code(bot, event)
    except Exception as error:
        await repository.fail_payment_delivery(event.transaction_id, repr(error))
        raise
    await repository.complete_payment_delivery(event.transaction_id, message_id)
    return {"delivered": True, "already_delivered": False}


async def _deliver_referral_reward_once(
    bot: Bot, repository: SQLiteRepository, event: ReferralRewardEvent
) -> dict[str, bool]:
    reward_id = str(event.reward_id)
    payload_hash = _payload_hash(event)
    claim = await repository.claim_referral_reward_delivery(
        reward_id,
        event.transaction_id,
        payload_hash,
        API_DELIVERY_LEASE_SECONDS,
    )
    if claim == "already_delivered":
        return {"delivered": True, "already_delivered": True}
    if claim == "in_progress":
        raise DeliveryInProgressError
    try:
        message_id = await _deliver_referral_reward(bot, event)
    except Exception as error:
        await repository.fail_referral_reward_delivery(reward_id, repr(error))
        raise
    await repository.complete_referral_reward_delivery(reward_id, message_id)
    return {"delivered": True, "already_delivered": False}


async def _deliver_payment_code(bot: Bot, event: PaymentCodeEvent) -> int | None:
    message = await send_flood_safe(
        lambda: bot.send_message(
            event.recipient_telegram_id,
            _code_message(event),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Как активировать код?", callback_data="asfaq_code")],
                    [InlineKeyboardButton(text="Как поменять регион?", callback_data="asfaq_region")],
                ]
            ),
        )
    )
    return _message_id(message)


async def _deliver_referral_reward(
    bot: Bot, event: ReferralRewardEvent
) -> int | None:
    message = await send_flood_safe(
        lambda: bot.send_message(
            event.recipient_telegram_id,
            "🎉 <b>Ваш реферал совершил первую оплату!</b>\n\n"
            "Ваш подарочный код App Store:\n\n"
            f"<code>{html.escape(event.key)}</code>",
            parse_mode=ParseMode.HTML,
        )
    )

    try:
        referred = (
            str(event.referred_telegram_id)
            if event.referred_telegram_id is not None
            else "не указан"
        )
        await send_flood_safe(
            lambda: bot.send_message(
                _manager_chat_id(),
                "🎁 <b>Выдан реферальный бонус</b>\n"
                f"Получатель: <code>{event.recipient_telegram_id}</code>\n"
                f"Реферал: <code>{referred}</code>\n"
                f"Транзакция: <code>{html.escape(event.transaction_id)}</code>\n"
                f"Код: <tg-spoiler>{html.escape(event.key)}</tg-spoiler>",
                parse_mode=ParseMode.HTML,
            )
        )
    except Exception:
        # The customer already has the reward. An internal alert must never
        # make the API resend the same code to that customer.
        logger.exception("Could not post referral reward alert to manager chat")
    return _message_id(message)


async def _send_test(bot: Bot, recipient_telegram_id: int) -> None:
    await send_flood_safe(
        lambda: bot.send_message(
            recipient_telegram_id,
            "✅ <b>Проверка Telegram-доставки 2PAY</b>\n\n"
            "Бот может отправлять сообщения. Платёжные данные и коды не использовались.",
            parse_mode=ParseMode.HTML,
        )
    )


async def _send_html(bot: Bot, payload: dict[str, object]) -> None:
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        raise WebhookInputError("text is required")
    chat_id_value = payload.get("chat_id")
    chat_id = _manager_chat_id() if chat_id_value == 0 else _nonzero_int(chat_id_value, "chat_id")
    await send_flood_safe(
        lambda: bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)
    )


def _nonzero_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value == 0:
        raise WebhookInputError(f"{name} must be a non-zero integer")
    return value


def _manager_chat_id() -> int:
    from config.config_env import ADMIN_CHAT_ID

    try:
        return _nonzero_int(int(ADMIN_CHAT_ID), "ADMIN_CHAT_ID")
    except (TypeError, ValueError) as error:
        raise WebhookInputError("ADMIN_CHAT_ID is required for manager events") from error


def _code_message(event: PaymentCodeEvent) -> str:
    region_names = {"tr": "Турция", "us": "США"}
    region = html.escape(region_names.get(event.region, event.region.upper()))
    code = html.escape(event.code)
    return (
        "✅ <b>Оплата подтверждена</b>\n\n"
        f"Ваш код App Store {region} номиналом <b>{event.nominal}</b>:\n\n"
        f"<code>{code}</code>\n\n"
        "Активируйте его в App Store на устройстве с нужным регионом.\n\n"
        "2PAY"
    )


def build_app(bot: Bot, repository: SQLiteRepository) -> web.Application:
    app = web.Application()
    app[BOT_APP_KEY] = bot
    app[STORAGE_APP_KEY] = repository
    app.router.add_post(TWO_PAY_API_WEBHOOK_PATH, _handle)
    app.router.add_get("/healthz", _healthz)
    return app


async def _healthz(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def start_webhook_server(
    bot: Bot, repository: SQLiteRepository
) -> web.AppRunner:
    if not TWO_PAY_API_WEBHOOK_TOKEN:
        raise RuntimeError("TWO_PAY_API_WEBHOOK_TOKEN is required")
    runner = web.AppRunner(build_app(bot, repository), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, TWO_PAY_API_WEBHOOK_HOST, TWO_PAY_API_WEBHOOK_PORT)
    await site.start()
    logger.info(
        "2PAY event webhook listens on http://%s:%s%s",
        TWO_PAY_API_WEBHOOK_HOST,
        TWO_PAY_API_WEBHOOK_PORT,
        TWO_PAY_API_WEBHOOK_PATH,
    )
    return runner
