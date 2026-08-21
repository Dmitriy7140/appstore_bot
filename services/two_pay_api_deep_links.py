"""Send normalized Telegram deep-link starts to the 2PAY API."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import aiohttp

from config.config_env import (
    TWO_PAY_API_DEEP_LINK_TIMEOUT_SECONDS,
    TWO_PAY_API_DEEP_LINK_URL,
    TWO_PAY_API_INGEST_TOKEN,
)
from config.utils import logger


_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def send_deep_link_event(
    *,
    telegram_id: int,
    link: str,
    is_ref: bool,
    referrer_telegram_id: int | None = None,
) -> None:
    """Post one `/start` event, reusing its UUID across network retries."""
    if not TWO_PAY_API_DEEP_LINK_URL or not TWO_PAY_API_INGEST_TOKEN:
        logger.error("2PAY deep-link API is not configured")
        return
    idempotency_key = str(uuid4())
    payload = {
        "telegram_id": telegram_id,
        "link": link,
        "is_ref": is_ref,
        "referrer_telegram_id": referrer_telegram_id,
    }
    headers = {
        "Idempotency-Key": idempotency_key,
        "X-Bot-API-Token": TWO_PAY_API_INGEST_TOKEN,
    }
    timeout = aiohttp.ClientTimeout(total=TWO_PAY_API_DEEP_LINK_TIMEOUT_SECONDS)
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    TWO_PAY_API_DEEP_LINK_URL,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status in {200, 201}:
                        return
                    response_text = (await response.text())[:500]
                    if response.status < 500:
                        logger.warning(
                            "2PAY rejected deep-link event %s with HTTP %s: %s",
                            idempotency_key,
                            response.status,
                            response_text,
                        )
                        return
                    raise RuntimeError(f"2PAY deep-link API returned HTTP {response.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
            if attempt == 2:
                logger.exception("Could not send deep-link event %s to 2PAY", idempotency_key)
                return
            await asyncio.sleep(0.5 * (2**attempt))


def queue_deep_link_event(**kwargs) -> None:
    """Start delivery without delaying the user's first bot menu."""
    task = asyncio.create_task(send_deep_link_event(**kwargs))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_log_unexpected_failure)


def _log_unexpected_failure(task: asyncio.Task) -> None:
    _BACKGROUND_TASKS.discard(task)
    try:
        task.result()
    except Exception:
        logger.exception("Unexpected deep-link delivery task failure")
