"""Build the daily site and TMA sales post from the authoritative 2PAY API."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from services.sales_period import MOSCOW_TIMEZONE
from services.two_pay_api_client import DailySales, get_daily_sales


def latest_closed_period_end_date(now: datetime | None = None) -> date:
    """Get the end date of the last fully closed Moscow calendar day."""
    if now is None:
        now = datetime.now(MOSCOW_TIMEZONE)
    elif now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    else:
        now = now.astimezone(MOSCOW_TIMEZONE)

    return now.date()


async def build_daily_sales_report(period_end_date: date | None = None) -> str:
    """Format the report for the last closed day, or the explicit period end."""
    if period_end_date is None:
        period_end_date = latest_closed_period_end_date()
    site_turkey, site_usa, tma_turkey, tma_usa, site_ps, tma_ps = await asyncio.gather(
        get_daily_sales("appstore_tr", period_end_date, source="site"),
        get_daily_sales("appstore_us", period_end_date, source="site"),
        get_daily_sales("appstore_tr", period_end_date, source="tma"),
        get_daily_sales("appstore_us", period_end_date, source="tma"),
        get_daily_sales("ps_codes", period_end_date, source="site"),
        get_daily_sales("ps_codes", period_end_date, source="tma"),
    )
    return format_daily_sales_report(
        period_end_date, site_turkey, site_usa, tma_turkey, tma_usa, site_ps, tma_ps
    )


def format_daily_sales_report(
    period_end_date: date,
    site_turkey: DailySales,
    site_usa: DailySales,
    tma_turkey: DailySales,
    tma_usa: DailySales,
    site_ps: DailySales,
    tma_ps: DailySales,
) -> str:
    """Render separate source totals and their combined total as Telegram HTML."""
    report_date = period_end_date - timedelta(days=1)
    total_rub = sum(
        sales.sales_rub for sales in (site_turkey, site_usa, tma_turkey, tma_usa, site_ps, tma_ps)
    )
    return "\n\n".join(
        [
            _source_report("САЙТ", report_date, site_turkey, site_usa, site_ps),
            _source_report("TMA", report_date, tma_turkey, tma_usa, tma_ps),
            f"💰 <b>Общий итог: {_format_number(total_rub)} ₽</b>",
        ]
    )


def _source_report(
    title: str,
    report_date: date,
    turkey: DailySales,
    usa: DailySales,
    ps: DailySales,
) -> str:
    """Render code sales and their total for one purchase source."""
    total_rub = turkey.sales_rub + usa.sales_rub + ps.sales_rub
    return "\n".join(
        [
            f"📊 {title} <b>Сводка за {report_date:%d.%m.%Y} (Автовыдача)</b>",
            "",
            _sales_line("🇹🇷", "App Store Турция", turkey),
            _sales_line("🇺🇸", "App Store США", usa),
            _sales_line("🎮", "Коды PS", ps),
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
