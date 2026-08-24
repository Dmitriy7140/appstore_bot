from datetime import date
import unittest
from unittest.mock import AsyncMock, patch

from services import two_pay_api_client as client
from services.two_pay_api_client import (
    DailySales,
    MarketingSalesSync,
    TwoPayApiError,
    get_daily_sales,
    get_code_inventory,
    refresh_code_inventory,
    register_bot_user,
    sync_daily_marketing_sales,
)


class TwoPayApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_sales_posts_expected_contract(self) -> None:
        request = AsyncMock(
            return_value={
                "field": "appstore_tr",
                "sales_rub": 17100,
                "sales_count": 14,
                "period_started_at": "2026-08-23T00:20:00+03:00",
                "period_ended_at": "2026-08-24T00:20:00+03:00",
            }
        )
        with patch("services.two_pay_api_client._request", request):
            result = await get_daily_sales("appstore_tr", date(2026, 8, 24))

        self.assertEqual(result, DailySales("appstore_tr", sales_rub=17100, sales_count=14))
        request.assert_awaited_once_with(
            "POST",
            "/v1/bot/daily-sales",
            json_body={"field": "appstore_tr", "period_end_date": "2026-08-24"},
        )

    async def test_marketing_sales_sync_posts_the_same_period_end_date(self) -> None:
        request = AsyncMock(
            return_value={
                "report_date": "23.08",
                "sales_rub": 20290,
                "sales_count": 18,
                "marketing_sheet_row": 7,
                "period_started_at": "2026-08-23T00:20:00+03:00",
                "period_ended_at": "2026-08-24T00:20:00+03:00",
            }
        )
        with patch("services.two_pay_api_client._request", request):
            result = await sync_daily_marketing_sales(date(2026, 8, 24))

        self.assertEqual(
            result,
            MarketingSalesSync(
                report_date="23.08",
                sales_rub=20_290,
                sales_count=18,
                marketing_sheet_row=7,
            ),
        )
        request.assert_awaited_once_with(
            "POST",
            "/v1/bot/daily-sales/marketing-report",
            json_body={"period_end_date": "2026-08-24"},
        )

    async def test_register_bot_user_posts_expected_contract(self) -> None:
        request = AsyncMock(
            return_value={"telegram_id": 12931239, "status": "registered"}
        )
        with patch("services.two_pay_api_client._request", request):
            await register_bot_user(12931239, "Two_Pay_User")

        request.assert_awaited_once_with(
            "POST",
            "/v1/bot/users",
            json_body={
                "telegram_id": 12931239,
                "telegram_username": "Two_Pay_User",
            },
        )

    async def test_register_bot_user_rejects_mismatched_response(self) -> None:
        request = AsyncMock(return_value={"telegram_id": 1, "status": "registered"})
        with patch("services.two_pay_api_client._request", request):
            with self.assertRaises(TwoPayApiError):
                await register_bot_user(12931239, None)

    async def test_code_inventory_contract_is_parsed_and_refresh_uses_long_timeout(self) -> None:
        inventory = {
            "total_available": 8,
            "regions": [
                {
                    "region": "tr",
                    "available": 7,
                    "nominals": [
                        {"nominal": 100, "available": 7, "cache_limit": 20}
                    ],
                },
                {
                    "region": "us",
                    "available": 1,
                    "nominals": [
                        {"nominal": 10, "available": 1, "cache_limit": 2}
                    ],
                },
            ],
        }
        request = AsyncMock(
            side_effect=[inventory, {"status": "refreshed", "inventory": inventory}]
        )
        with patch("services.two_pay_api_client._request", request):
            current = await get_code_inventory()
            refreshed = await refresh_code_inventory()

        self.assertEqual(current.total_available, 8)
        self.assertEqual(current.regions[0].nominals[0].nominal, 100)
        self.assertEqual(refreshed, current)
        self.assertEqual(
            request.await_args_list[0].args,
            ("GET", "/v1/bot/code-inventory"),
        )
        self.assertEqual(
            request.await_args_list[1].args,
            ("POST", "/v1/bot/code-inventory/refresh"),
        )
        self.assertEqual(
            request.await_args_list[1].kwargs["timeout_seconds"],
            client.TWO_PAY_API_INVENTORY_REFRESH_TIMEOUT_SECONDS,
        )

    async def test_code_inventory_rejects_inconsistent_totals(self) -> None:
        request = AsyncMock(
            return_value={
                "total_available": 99,
                "regions": [
                    {"region": "tr", "available": 0, "nominals": []}
                ],
            }
        )
        with patch("services.two_pay_api_client._request", request):
            with self.assertRaises(TwoPayApiError):
                await get_code_inventory()


if __name__ == "__main__":
    unittest.main()
