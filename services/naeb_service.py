from aiogram.types import Message


def parse_start_payload(message: Message) -> str | None:
    if not message.text:
        return None

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        return None

    return parts[1].strip()