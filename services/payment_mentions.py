"""Render numeric payment mentions with a Telegram display name."""
from __future__ import annotations

import html
import re
import logging

logger = logging.getLogger(__name__)
MENTION = re.compile(r'<a href=["\']tg://user\?id=([1-9][0-9]{0,15})["\']>(?:id)?\1</a>')
RECIPIENT = re.compile(r'(?m)^💬 (?:📧 )?(?:@[A-Za-z0-9_]+ · )?(?:id)?([1-9][0-9]{0,15})$')


async def name_payment_mentions(bot, text: str) -> str:
    if "💳 <b>Оплата" in text:
        text = RECIPIENT.sub(lambda match: f'💬 <a href="tg://user?id={match.group(1)}">{match.group(1)}</a>', text)
    # Only trusted numeric placeholders are changed. Existing named links stay intact.
    names = {}
    for match in MENTION.finditer(text):
        user_id = int(match.group(1))
        if user_id in names:
            continue
        try:
            chat = await bot.get_chat(user_id)
            parts = [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
            name = " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
            username = getattr(chat, "username", None)
            names[user_id] = name or (f"@{username}" if username else "Покупатель")
        except Exception as error:
            # An optional profile lookup cannot delay a committed paid notification.
            logger.warning("Payment recipient name lookup unavailable (%s)", type(error).__name__)
            names[user_id] = "Покупатель"
    return MENTION.sub(lambda match: f'<a href="tg://user?id={match.group(1)}">{html.escape(names[int(match.group(1))])}</a>', text)
