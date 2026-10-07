"""Storefront buyer delivery; the API owns payment, the bot owns presentation."""
from __future__ import annotations

import html
import re


def buyer_notification(payload: dict) -> dict:
    from services.two_pay_api_webhook import WebhookInputError, _positive_int

    expected = {"delivery_id", "invoice_id", "recipient_telegram_id", "code", "product_type", "region", "nominal", "currency"}
    if set(payload) != expected:
        raise WebhookInputError("Invalid Storefront buyer fields")
    invoice_id = _positive_int(payload["invoice_id"], "invoice_id")
    recipient = _positive_int(payload["recipient_telegram_id"], "recipient_telegram_id")
    nominal = _positive_int(payload["nominal"], "nominal")
    delivery_id = payload["delivery_id"]
    if not isinstance(delivery_id, str) or not re.fullmatch(rf"storefront:{invoice_id}:buyer:[0-9a-f]{{64}}", delivery_id):
        raise WebhookInputError("Invalid Storefront buyer delivery ID")
    code = payload["code"]
    if not isinstance(code, str) or not code or len(code) > 512:
        raise WebhookInputError("Invalid Storefront code")
    kind = payload["product_type"]
    if kind not in ("appstore_code", "psn_wallet_code"):
        raise WebhookInputError("Unsupported code product")
    region, currency = payload["region"], payload["currency"]
    if region not in ("tr", "us") or currency not in ("TRY", "USD"):
        raise WebhookInputError("Invalid code region/currency")
    product = "App Store" if kind == "appstore_code" else "PlayStation"
    country = "Турция" if region == "tr" else "США"
    text = (
        "✅ <b>Оплата подтверждена</b>\n\n"
        f"Код {product} ({country}), <b>{nominal} {currency}</b>:\n"
        f"<code>{html.escape(code)}</code>\n\n"
        f"Заказ 2PAY №{invoice_id}"
    )
    return {"delivery_id": delivery_id, "chat_id": recipient, "text": text}


async def deliver_storefront_code(bot, repository, payload: dict):
    from services.two_pay_api_webhook import _deliver_html_once
    return await _deliver_html_once(bot, repository, buyer_notification(payload))
