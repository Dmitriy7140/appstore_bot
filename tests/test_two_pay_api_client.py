import unittest
from unittest.mock import AsyncMock, patch

from services.two_pay_api_client import TwoPayApiError, register_bot_user


class TwoPayApiClientTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
