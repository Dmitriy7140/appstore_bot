"""Build the daily site and TMA sales post from the authoritative 2PAY API."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta

import pytz

from services.two_pay_api_client import DailySales, get_daily_sales


MOSCOW_TIMEZONE = pytz.timezone("Europe/Moscow")
DAY_CLOSE_TIME = time(0, 20)


def latest_closed_period_end_date(now: datetime | None = None) -> date:
    """Get the end date of the last fully closed [00:20; 00:20) Moscow period."""
    if now is None:
        now = datetime.now(MOSCOW_TIMEZONE)
    elif now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    else:
        now = now.astimezone(MOSCOW_TIMEZONE)

    today_close = now.replace(
        hour=DAY_CLOSE_TIME.hour,
        minute=DAY_CLOSE_TIME.minute,
        second=0,
        microsecond=0,
    )
    return now.date() if now >= today_close else now.date() - timedelta(days=1)


async def build_daily_sales_report(period_end_date: date | None = None) -> str:
    """Format the report for the last closed day, or the explicit period end."""
    if period_end_date is None:
        period_end_date = latest_closed_period_end_date()
    site_turkey, site_usa, tma_turkey, tma_usa = await asyncio.gather(
        get_daily_sales("appstore_tr", period_end_date, source="site"),
        get_daily_sales("appstore_us", period_end_date, source="site"),
        get_daily_sales("appstore_tr", period_end_date, source="tma"),
        get_daily_sales("appstore_us", period_end_date, source="tma"),
    )
    return format_daily_sales_report(
        period_end_date, site_turkey, site_usa, tma_turkey, tma_usa
    )


def format_daily_sales_report(
    period_end_date: date,
    site_turkey: DailySales,
    site_usa: DailySales,
    tma_turkey: DailySales,
    tma_usa: DailySales,
) -> str:
    """Render separate source totals and their combined total as Telegram HTML."""
    report_date = period_end_date - timedelta(days=1)
    total_rub = sum(
        sales.sales_rub for sales in (site_turkey, site_usa, tma_turkey, tma_usa)
    )
    return "\n\n".join(
        [
            _source_report("САЙТ", report_date, site_turkey, site_usa),
            _source_report("TMA", report_date, tma_turkey, tma_usa),
            f"💰 <b>Общий итог: {_format_number(total_rub)} ₽</b>",
        ]
    )


def _source_report(
    title: str,
    report_date: date,
    turkey: DailySales,
    usa: DailySales,
) -> str:
    """Render a Telegram HTML report; PS stays zero until its API field exists."""
    total_rub = turkey.sales_rub + usa.sales_rub
    return "\n".join(
        [
            f"📊 {title} <b>Сводка за {report_date:%d.%m.%Y} (Автовыдача)</b>",
            "",
            _sales_line("🇹🇷", "App Store Турция", turkey),
            _sales_line("🇺🇸", "App Store США", usa),
            "🎮 <b>Коды PS</b>: 0 код(ов) · 0 ₽",
            "",
            f"💸 <b>Всего: {_format_number(total_rub)} ₽</b>",
        ]
    )


def _sales_line(flag: str, title: str, sales: DailySales) -> str:
    return (
        f"{flag} <b>{title}</b>: {sales.sales_count} код(ов) · "
        f"{_format_number(sales.sales_rub)} ₽"
    )


def _format_number(value: int) -> str:
    return f"{value:,}".replace(",", "\u00a0")
