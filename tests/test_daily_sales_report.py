from datetime import date, datetime
import unittest
from unittest.mock import AsyncMock, call, patch

import pytz

from services.daily_sales_report import (
    build_daily_sales_report,
    format_daily_sales_report,
    latest_closed_period_end_date,
)
from services.two_pay_api_client import DailySales, MarketingSalesSync, TwoPayApiError


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
            DailySales("appstore_tr", sales_rub=17100, sales_count=14, source="site"),
            DailySales("appstore_us", sales_rub=3190, sales_count=4, source="site"),
            DailySales("appstore_tr", sales_rub=500, sales_count=1, source="tma"),
            DailySales("appstore_us", sales_rub=0, sales_count=0, source="tma"),
        )

        self.assertEqual(report, "\n".join([
            "📊 САЙТ <b>Сводка за 23.08.2026 (Автовыдача)</b>",
            "",
            "🇹🇷 <b>App Store Турция</b>: 14 код(ов) · 17\u00a0100 ₽",
            "🇺🇸 <b>App Store США</b>: 4 код(ов) · 3\u00a0190 ₽",
            "🎮 <b>Коды PS</b>: 0 код(ов) · 0 ₽",
            "",
            "💸 <b>Всего: 20\u00a0290 ₽</b>",
            "",
            "📊 TMA <b>Сводка за 23.08.2026 (Автовыдача)</b>",
            "",
            "🇹🇷 <b>App Store Турция</b>: 1 код(ов) · 500 ₽",
            "🇺🇸 <b>App Store США</b>: 0 код(ов) · 0 ₽",
            "🎮 <b>Коды PS</b>: 0 код(ов) · 0 ₽",
            "",
            "💸 <b>Всего: 500 ₽</b>",
            "",
            "💰 <b>Общий итог: 20\u00a0790 ₽</b>",
        ]))

    async def test_report_requests_both_fields_for_each_source_and_same_day(self) -> None:
        request = AsyncMock(
            side_effect=[
                DailySales("appstore_tr", sales_rub=100, sales_count=1, source="site"),
                DailySales("appstore_us", sales_rub=200, sales_count=2, source="site"),
                DailySales("appstore_tr", sales_rub=300, sales_count=3, source="tma"),
                DailySales("appstore_us", sales_rub=400, sales_count=4, source="tma"),
            ]
        )
        with patch("services.daily_sales_report.get_daily_sales", request):
            report = await build_daily_sales_report(date(2026, 8, 24))

        self.assertIn("Всего: 300 ₽", report)
        self.assertIn("Всего: 700 ₽", report)
        self.assertIn("Общий итог: 1\u00a0000 ₽", report)

        self.assertCountEqual(
            request.await_args_list,
            [
                call("appstore_tr", date(2026, 8, 24), source="site"),
                call("appstore_us", date(2026, 8, 24), source="site"),
                call("appstore_tr", date(2026, 8, 24), source="tma"),
                call("appstore_us", date(2026, 8, 24), source="tma"),
            ],
        )

    async def test_report_does_not_hide_source_failure_as_zero_sales(self) -> None:
        with patch("services.daily_sales_report.get_daily_sales", AsyncMock(side_effect=TwoPayApiError)):
            with self.assertRaises(TwoPayApiError):
                await build_daily_sales_report(date(2026, 8, 24))

    async def test_scheduled_report_syncs_marketing_sheet_for_the_same_day(self) -> None:
        from services import scheduler

        period_end_date = date(2026, 8, 24)
        sync = AsyncMock(
            return_value=MarketingSalesSync(
                report_date="23.08",
                sales_rub=20_290,
                sales_count=18,
                marketing_sheet_row=7,
            )
        )
        build_report = AsyncMock(return_value="daily report")
        send = AsyncMock()
        with (
            patch.object(scheduler, "DAILY_SALES_REPORT_CHAT_ID", -100123),
            patch("services.scheduler.latest_closed_period_end_date", return_value=period_end_date),
            patch("services.scheduler.sync_daily_marketing_sales", sync),
            patch("services.scheduler.build_daily_sales_report", build_report),
            patch("services.scheduler.send_flood_safe", send),
        ):
            await scheduler._send_daily_sales_report(object())

        sync.assert_awaited_once_with(period_end_date)
        build_report.assert_awaited_once_with(period_end_date)


if __name__ == "__main__":
    unittest.main()
