"""Calendar-day boundaries shared by the sales report and API client."""
from datetime import date, datetime, time, timedelta

import pytz


MOSCOW_TIMEZONE = pytz.timezone("Europe/Moscow")


def calendar_sales_period(period_end_date: date) -> tuple[datetime, datetime]:
    """Return [previous midnight, end-date midnight) in Moscow time."""
    return (
        MOSCOW_TIMEZONE.localize(datetime.combine(period_end_date - timedelta(days=1), time.min)),
        MOSCOW_TIMEZONE.localize(datetime.combine(period_end_date, time.min)),
    )
