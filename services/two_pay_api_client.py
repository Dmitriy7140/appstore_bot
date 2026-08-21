"""Small authenticated client for the private appstore-bot API contract."""
from __future__ import annotations

import json
from typing import Any, Literal

import aiohttp

from config.config_env import (
    TWO_PAY_API_AUDIENCE_TOKEN,
    TWO_PAY_API_BASE_URL,
    TWO_PAY_API_INGEST_TOKEN,
    TWO_PAY_API_TIMEOUT_SECONDS,
)


Audience = Literal["all", "paid", "never_paid"]


class TwoPayApiError(RuntimeError):
    """A private API request could not be completed successfully."""


def _require_token(token: str, name: str) -> str:
    if not token:
        raise TwoPayApiError(f"{name} is not configured")
    return token


async def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    audience: bool = False,
) -> Any:
    token = _require_token(
        TWO_PAY_API_AUDIENCE_TOKEN if audience else TWO_PAY_API_INGEST_TOKEN,
        "TWO_PAY_API_AUDIENCE_TOKEN" if audience else "TWO_PAY_API_INGEST_TOKEN",
    )
    header_name = "X-Audience-Token" if audience else "X-Bot-API-Token"
    timeout = aiohttp.ClientTimeout(total=TWO_PAY_API_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method,
                f"{TWO_PAY_API_BASE_URL}{path}",
                json=json_body,
                params=params,
                headers={header_name: token},
            ) as response:
                status = response.status
                body = await response.text()
    except (aiohttp.ClientError, TimeoutError) as error:
        raise TwoPayApiError("2PAY API is unavailable") from error

    if status >= 400:
        raise TwoPayApiError(f"2PAY API returned HTTP {status}: {body[:500]}")
    if status == 204 or not body:
        return None
    try:
        return json.loads(body)
    except ValueError as error:
        raise TwoPayApiError("2PAY API returned invalid JSON") from error


async def get_audience(segment: Audience) -> list[int]:
    users: list[int] = []
    cursor: int | None = None
    while True:
        params: dict[str, Any] = {"segment": segment, "limit": 1000}
        if cursor is not None:
            params["cursor"] = cursor
        page = await _request("GET", "/v1/audiences/telegram-users", params=params, audience=True)
        if not isinstance(page, dict) or not isinstance(page.get("users"), list):
            raise TwoPayApiError("2PAY API returned invalid audience page")
        for user in page["users"]:
            if not isinstance(user, dict) or not isinstance(user.get("telegram_id"), int):
                raise TwoPayApiError("2PAY API returned invalid Telegram ID")
            users.append(user["telegram_id"])
        next_cursor = page.get("next_cursor")
        if next_cursor is None:
            return users
        if not isinstance(next_cursor, int) or next_cursor <= 0:
            raise TwoPayApiError("2PAY API returned invalid audience cursor")
        cursor = next_cursor


async def register_bot_user(
    telegram_id: int,
    telegram_username: str | None,
) -> None:
    """Idempotently register a Telegram user before showing the start menu."""
    payload: dict[str, Any] = {"telegram_id": telegram_id}
    if telegram_username:
        payload["telegram_username"] = telegram_username
    response = await _request("POST", "/v1/bot/users", json_body=payload)
    if (
        not isinstance(response, dict)
        or response.get("status") != "registered"
        or response.get("telegram_id") != telegram_id
    ):
        raise TwoPayApiError("2PAY API returned invalid user registration response")
