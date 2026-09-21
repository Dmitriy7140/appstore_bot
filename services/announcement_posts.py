"""Serializable announcement drafts and the shared preview/delivery renderer."""
from uuid import uuid4
from urllib.parse import urlsplit

from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder


PROMO_CALLBACK_PREFIX = "announce_promo:"
MAX_BUTTONS = InlineKeyboardBuilder.max_buttons


def draft_post(message: Message) -> dict:
    markup = message.reply_markup
    return {
        "id": uuid4().hex,
        "source_chat_id": message.chat.id,
        "source_message_id": message.message_id,
        "reply_markup": (
            markup.model_dump(mode="json", exclude_none=True)
            if markup else {"inline_keyboard": []}
        ),
    }


def button_count(post: dict) -> int:
    return sum(len(row) for row in post["reply_markup"]["inline_keyboard"])


def post_markup(post: dict) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup.model_validate(post["reply_markup"])
    # Validate the total count and each row against aiogram's Telegram limits.
    InlineKeyboardBuilder(markup=markup.inline_keyboard)
    return markup


def valid_button_url(value: str) -> bool:
    if any(char.isspace() or ord(char) < 32 for char in value):
        return False
    try:
        parts = urlsplit(value)
        _ = parts.port
        return (
            parts.scheme.lower() in {"http", "https", "tg"}
            and bool(parts.hostname)
            and parts.username is None and parts.password is None
        )
    except ValueError:
        return False


def reachable_posts(data: dict) -> list[dict]:
    """Exclude abandoned promotions after removing a button from the draft."""
    drafts = data["post_drafts"]
    pending = [data["root_post_id"]]
    result = []
    seen = set()
    while pending:
        post_id = pending.pop()
        if post_id in seen:
            continue
        seen.add(post_id)
        post = drafts[post_id]
        post_markup(post)
        result.append(post)
        for row in post["reply_markup"]["inline_keyboard"]:
            for button in row:
                callback = button.get("callback_data", "")
                if callback.startswith(PROMO_CALLBACK_PREFIX):
                    target = callback.removeprefix(PROMO_CALLBACK_PREFIX)
                    if target in drafts:
                        pending.append(target)
    return result


async def copy_post(bot, chat_id: int, post: dict):
    # Telegram copies original entities, captions, links and media unchanged.
    # Only the assembled keyboard is replaced, for previews and real sends alike.
    return await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=post["source_chat_id"],
        message_id=post["source_message_id"],
        reply_markup=post_markup(post),
    )
