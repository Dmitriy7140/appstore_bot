"""Small authenticated client for the private appstore-bot API contract."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Any, Literal

import aiohttp

from services.sales_period import calendar_sales_period
from config.config_env import (
    TWO_PAY_API_AUDIENCE_TOKEN,
    TWO_PAY_API_BASE_URL,
    TWO_PAY_API_INGEST_TOKEN,
    TWO_PAY_API_TIMEOUT_SECONDS,
)


Audience = Literal["all", "paid", "never_paid"]
DailySalesField = Literal["appstore_tr", "appstore_us", "ps_codes"]
DailySalesSource = Literal["site", "tma"]


@dataclass(frozen=True, slots=True)
class CodeNominalStock:
    nominal: int
    available: int


@dataclass(frozen=True, slots=True)
class CodeRegionStock:
    region: str
    available: int
    nominals: tuple[CodeNominalStock, ...]


@dataclass(frozen=True, slots=True)
class CodeInventoryStock:
    total_available: int
    regions: tuple[CodeRegionStock, ...]


@dataclass(frozen=True, slots=True)
class DailySales:
    field: DailySalesField
    sales_rub: int
    sales_count: int
    source: DailySalesSource


@dataclass(frozen=True, slots=True)
class MarketingSalesSync:
    report_date: str
    sales_rub: int
    sales_count: int
    marketing_sheet_row: int


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
    timeout_seconds: float | None = None,
) -> Any:
    token = _require_token(
        TWO_PAY_API_AUDIENCE_TOKEN if audience else TWO_PAY_API_INGEST_TOKEN,
        "TWO_PAY_API_AUDIENCE_TOKEN" if audience else "TWO_PAY_API_INGEST_TOKEN",
    )
    header_name = "X-Audience-Token" if audience else "X-Bot-API-Token"
    timeout = aiohttp.ClientTimeout(
        total=TWO_PAY_API_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )
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


async def get_code_inventory() -> CodeInventoryStock:
    response = await _request("GET", "/v1/bot/code-inventory")
    return _parse_code_inventory(response)


async def get_daily_sales(
    field: DailySalesField,
    period_end_date: date,
    *,
    source: DailySalesSource,
) -> DailySales:
    """Return confirmed, non-referral sales for one source and Moscow day."""
    response = await _request(
        "POST",
        "/v1/bot/daily-sales",
        json_body={
            "field": field,
            "period_end_date": period_end_date.isoformat(),
            "source": source,
        },
    )
    sales = _parse_daily_sales(response)
    if sales.field != field:
        raise TwoPayApiError("2PAY API returned daily sales for an unexpected field")
    if sales.source != source:
        raise TwoPayApiError("2PAY API returned daily sales for an unexpected source")
    _validate_sales_period(response, period_end_date)
    return sales


async def sync_daily_marketing_sales(
    period_end_date: date,
) -> MarketingSalesSync:
    """Write the combined App Store and PlayStation sales for one Moscow day to Google Sheets."""
    response = await _request(
        "POST",
        "/v1/bot/daily-sales/marketing-report",
        json_body={"period_end_date": period_end_date.isoformat()},
    )
    sales = _parse_marketing_sales_sync(response)
    expected_report_date = (period_end_date - timedelta(days=1)).strftime("%d.%m")
    if sales.report_date != expected_report_date:
        raise TwoPayApiError("2PAY API returned marketing sales for an unexpected date")
    _validate_sales_period(response, period_end_date)
    return sales


def _validate_sales_period(value: dict[str, Any], period_end_date: date) -> None:
    """Reject a shifted, incomplete or differently dated API period."""
    expected_start, expected_end = calendar_sales_period(period_end_date)
    try:
        started_at = datetime.fromisoformat(value["period_started_at"])
        ended_at = datetime.fromisoformat(value["period_ended_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise TwoPayApiError("2PAY API returned invalid sales period") from error
    if started_at.tzinfo is None or ended_at.tzinfo is None:
        raise TwoPayApiError("2PAY API returned a sales period without timezone")
    if started_at != expected_start or ended_at != expected_end:
        raise TwoPayApiError("2PAY API returned an unexpected Moscow calendar sales period")


def _parse_code_inventory(value: Any) -> CodeInventoryStock:
    if not isinstance(value, dict):
        raise TwoPayApiError("2PAY API returned invalid code inventory")
    total_available = value.get("total_available")
    raw_regions = value.get("regions")
    if not _is_non_negative_int(total_available) or not isinstance(raw_regions, list):
        raise TwoPayApiError("2PAY API returned invalid code inventory")

    regions: list[CodeRegionStock] = []
    for raw_region in raw_regions:
        if not isinstance(raw_region, dict):
            raise TwoPayApiError("2PAY API returned invalid code inventory region")
        region = raw_region.get("region")
        available = raw_region.get("available")
        raw_nominals = raw_region.get("nominals")
        if (
            not isinstance(region, str)
            or not region
            or not _is_non_negative_int(available)
            or not isinstance(raw_nominals, list)
        ):
            raise TwoPayApiError("2PAY API returned invalid code inventory region")

        nominals: list[CodeNominalStock] = []
        for raw_nominal in raw_nominals:
            if not isinstance(raw_nominal, dict):
                raise TwoPayApiError("2PAY API returned invalid code inventory nominal")
            nominal = raw_nominal.get("nominal")
            nominal_available = raw_nominal.get("available")
            if (
                not _is_positive_int(nominal)
                or not _is_non_negative_int(nominal_available)
            ):
                raise TwoPayApiError("2PAY API returned invalid code inventory nominal")
            nominals.append(
                CodeNominalStock(
                    nominal=nominal,
                    available=nominal_available,
                )
            )
        if available != sum(item.available for item in nominals):
            raise TwoPayApiError("2PAY API returned inconsistent code inventory region")
        regions.append(
            CodeRegionStock(
                region=region,
                available=available,
                nominals=tuple(nominals),
            )
        )

    if total_available != sum(region.available for region in regions):
        raise TwoPayApiError("2PAY API returned inconsistent code inventory total")
    return CodeInventoryStock(total_available=total_available, regions=tuple(regions))


def _parse_daily_sales(value: Any) -> DailySales:
    if not isinstance(value, dict):
        raise TwoPayApiError("2PAY API returned invalid daily sales")
    field = value.get("field")
    sales_rub = value.get("sales_rub")
    sales_count = value.get("sales_count")
    source = value.get("source")
    if (
        field not in {"appstore_tr", "appstore_us", "ps_codes"}
        or source not in ("site", "tma")
        or not _is_non_negative_int(sales_rub)
        or not _is_non_negative_int(sales_count)
    ):
        raise TwoPayApiError("2PAY API returned invalid daily sales")
    return DailySales(
        field=field, sales_rub=sales_rub, sales_count=sales_count, source=source
    )


def _parse_marketing_sales_sync(value: Any) -> MarketingSalesSync:
    if not isinstance(value, dict):
        raise TwoPayApiError("2PAY API returned invalid marketing sales")
    report_date = value.get("report_date")
    sales_rub = value.get("sales_rub")
    sales_count = value.get("sales_count")
    marketing_sheet_row = value.get("marketing_sheet_row")
    if (
        not isinstance(report_date, str)
        or not report_date
        or not _is_non_negative_int(sales_rub)
        or not _is_non_negative_int(sales_count)
        or not _is_positive_int(marketing_sheet_row)
    ):
        raise TwoPayApiError("2PAY API returned invalid marketing sales")
    return MarketingSalesSync(
        report_date=report_date,
        sales_rub=sales_rub,
        sales_count=sales_count,
        marketing_sheet_row=marketing_sheet_row,
    )


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return _is_non_negative_int(value) and value > 0
