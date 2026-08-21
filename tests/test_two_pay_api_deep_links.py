import json
import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from services import two_pay_api_deep_links as deep_links


class DeepLinkApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_network_retry_reuses_one_idempotency_key(self) -> None:
        requests = []

        async def handler(request: web.Request) -> web.Response:
            requests.append(
                {
                    "key": request.headers["Idempotency-Key"],
                    "token": request.headers["X-Bot-API-Token"],
                    "body": json.loads((await request.read()).decode()),
                }
            )
            status = 503 if len(requests) == 1 else 201
            return web.json_response({"ok": status == 201}, status=status)

        app = web.Application()
        app.router.add_post("/v1/bot/deep-links", handler)
        original_url = deep_links.TWO_PAY_API_DEEP_LINK_URL
        original_token = deep_links.TWO_PAY_API_INGEST_TOKEN
        original_timeout = deep_links.TWO_PAY_API_DEEP_LINK_TIMEOUT_SECONDS
        try:
            async with TestServer(app) as server:
                deep_links.TWO_PAY_API_DEEP_LINK_URL = str(
                    server.make_url("/v1/bot/deep-links")
                )
                deep_links.TWO_PAY_API_INGEST_TOKEN = "ingest-secret"
                deep_links.TWO_PAY_API_DEEP_LINK_TIMEOUT_SECONDS = 3
                await deep_links.send_deep_link_event(
                    telegram_id=12931239,
                    link="ref_987654321",
                    is_ref=True,
                    referrer_telegram_id=987654321,
                )
        finally:
            deep_links.TWO_PAY_API_DEEP_LINK_URL = original_url
            deep_links.TWO_PAY_API_INGEST_TOKEN = original_token
            deep_links.TWO_PAY_API_DEEP_LINK_TIMEOUT_SECONDS = original_timeout

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["key"], requests[1]["key"])
        self.assertEqual(requests[0]["token"], "ingest-secret")
        self.assertEqual(
            requests[0]["body"],
            {
                "telegram_id": 12931239,
                "link": "ref_987654321",
                "is_ref": True,
                "referrer_telegram_id": 987654321,
            },
        )


if __name__ == "__main__":
    unittest.main()
