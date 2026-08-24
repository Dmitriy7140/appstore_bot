from datetime import date, datetime
import unittest
from unittest.mock import AsyncMock, call, patch

import pytz

from services.daily_sales_report import (
    build_daily_sales_report,
    format_daily_sales_report,
    latest_closed_period_end_date,
)
from services.two_pay_api_client import DailySales


class DailySalesReportTests(unittest.IsolatedAsyncioTestCase):
    def test_last_closed_period_before_and_after_moscow_boundary(self) -> None:
        moscow = pytz.timezone("Europe/Moscow")
        self.assertEqual(
            latest_closed_period_end_date(moscow.localize(datetime(2026, 8, 24, 0, 19))),
            date(2026, 8, 23),
        )
        self.assertEqual(
            latest_closed_period_end_date(moscow.localize(datetime(2026, 8, 24, 0, 20))),
            date(2026, 8, 24),
        )

    def test_report_has_required_categories_and_total(self) -> None:
        report = format_daily_sales_report(
            date(2026, 8, 24),
            DailySales("appstore_tr", sales_rub=17100, sales_count=14),
            DailySales("appstore_us", sales_rub=3190, sales_count=4),
        )

        self.assertIn("Сводка за 23.08.2026", report)
        self.assertIn("App Store Турция</b>: 14 код(ов) · 17\u00a0100 ₽", report)
        self.assertIn("App Store США</b>: 4 код(ов) · 3\u00a0190 ₽", report)
        self.assertIn("Коды PS</b>: 0 код(ов) · 0 ₽", report)
        self.assertIn("Итого: 20\u00a0290 ₽", report)

    async def test_report_requests_both_api_fields_for_period_end_date(self) -> None:
        request = AsyncMock(
            side_effect=[
                DailySales("appstore_tr", sales_rub=100, sales_count=1),
                DailySales("appstore_us", sales_rub=200, sales_count=2),
            ]
        )
        with patch("services.daily_sales_report.get_daily_sales", request):
            await build_daily_sales_report(date(2026, 8, 24))

        self.assertCountEqual(
            request.await_args_list,
            [
                call("appstore_tr", date(2026, 8, 24)),
                call("appstore_us", date(2026, 8, 24)),
            ],
        )


if __name__ == "__main__":
    unittest.main()
