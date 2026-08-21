import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from services import two_pay_api_webhook as webhook
from repository.sqlite_storage import SQLiteRepository


class _Request:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


class TwoPayApiWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._token = webhook.TWO_PAY_API_WEBHOOK_TOKEN
        self._max_age = webhook.TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS
        webhook.TWO_PAY_API_WEBHOOK_TOKEN = "shared-secret"
        webhook.TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS = 300

    def tearDown(self) -> None:
        webhook.TWO_PAY_API_WEBHOOK_TOKEN = self._token
        webhook.TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS = self._max_age

    def test_signature_accepts_the_exact_api_contract(self) -> None:
        body = json.dumps(
            {
                "event": "payment.code.v1",
                "payload": {
                    "transaction_id": "robokassa:42",
                    "recipient_telegram_id": 123456789,
                    "code": "AAAA-BBBB-CCCC-DDDD",
                    "region": "tr",
                    "nominal": 100,
                    "amount_rub": 400,
                },
            },
            separators=(",", ":"),
        ).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            b"shared-secret",
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        request = _Request(
            {
                "X-2PAY-Timestamp": timestamp,
                "X-2PAY-Signature": f"sha256={signature}",
            }
        )

        self.assertTrue(webhook._is_authenticated(request, body))
        event = webhook._payment_event(json.loads(body)["payload"])
        self.assertEqual(event.transaction_id, "robokassa:42")
        self.assertEqual(event.recipient_telegram_id, 123456789)

    def test_signature_rejects_a_modified_event(self) -> None:
        body = b'{"event":"telegram.test.v1","payload":{"recipient_telegram_id":1}}'
        request = _Request(
            {
                "X-2PAY-Timestamp": str(int(time.time())),
                "X-2PAY-Signature": "sha256=" + "0" * 64,
            }
        )

        self.assertFalse(webhook._is_authenticated(request, body))

    def test_payment_event_rejects_boolean_ids(self) -> None:
        with self.assertRaises(webhook.WebhookInputError):
            webhook._payment_event(
                {
                    "transaction_id": "robokassa:42",
                    "recipient_telegram_id": True,
                    "code": "AAAA-BBBB-CCCC-DDDD",
                    "region": "tr",
                    "nominal": 100,
                    "amount_rub": 400,
                }
            )

    def test_referral_reward_event_validates_uuid_and_recipient(self) -> None:
        event = webhook._referral_reward_event(
            {
                "reward_id": "550e8400-e29b-41d4-a716-446655440000",
                "recipient_telegram_id": 987654321,
                "referred_telegram_id": 12931239,
                "key": "AAAA-BBBB-CCCC-DDDD",
                "transaction_id": "robokassa:42",
            }
        )
        self.assertEqual(event.recipient_telegram_id, 987654321)
        with self.assertRaises(webhook.WebhookInputError):
            webhook._referral_reward_event(
                {
                    "reward_id": "not-a-uuid",
                    "recipient_telegram_id": True,
                    "key": "key",
                    "transaction_id": "robokassa:42",
                }
            )


class TwoPayApiWebhookHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteRepository(Path(self.temp_dir.name) / "bot.sqlite3")
        await self.repository.open()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp_dir.cleanup()

    async def test_authenticated_test_event_reaches_the_bot(self) -> None:
        class FakeBot:
            def __init__(self) -> None:
                self.messages: list[tuple[int, str]] = []

            async def send_message(self, chat_id: int, text: str, **_kwargs) -> None:
                self.messages.append((chat_id, text))

        original_token = webhook.TWO_PAY_API_WEBHOOK_TOKEN
        original_age = webhook.TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS
        webhook.TWO_PAY_API_WEBHOOK_TOKEN = "shared-secret"
        webhook.TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS = 300
        bot = FakeBot()
        try:
            async with TestServer(webhook.build_app(bot, self.repository)) as server:
                body = b'{"event":"telegram.test.v1","payload":{"recipient_telegram_id":123456789}}'
                timestamp = str(int(time.time()))
                signature = hmac.new(
                    b"shared-secret",
                    timestamp.encode() + b"." + body,
                    hashlib.sha256,
                ).hexdigest()
                async with ClientSession() as session:
                    response = await session.post(
                        f"{server.make_url(webhook.TWO_PAY_API_WEBHOOK_PATH)}",
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-2PAY-Timestamp": timestamp,
                            "X-2PAY-Signature": f"sha256={signature}",
                        },
                    )
                    self.assertEqual(response.status, 200)
                    self.assertEqual(await response.json(), {"ok": True, "delivered": True})
        finally:
            webhook.TWO_PAY_API_WEBHOOK_TOKEN = original_token
            webhook.TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS = original_age

        self.assertEqual(bot.messages[0][0], 123456789)

    async def test_referral_event_header_routes_direct_json(self) -> None:
        class FakeBot:
            pass

        original_token = webhook.TWO_PAY_API_WEBHOOK_TOKEN
        webhook.TWO_PAY_API_WEBHOOK_TOKEN = "shared-secret"
        body = json.dumps(
            {
                "reward_id": "550e8400-e29b-41d4-a716-446655440000",
                "recipient_telegram_id": 987654321,
                "referred_telegram_id": 12931239,
                "key": "AAAA-BBBB-CCCC-DDDD",
                "transaction_id": "robokassa:42",
            },
            separators=(",", ":"),
        ).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            b"shared-secret",
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        delivery = AsyncMock(return_value=73)
        try:
            with patch.object(webhook, "_deliver_referral_reward", delivery):
                async with TestServer(
                    webhook.build_app(FakeBot(), self.repository)
                ) as server:
                    async with ClientSession() as session:
                        response = await session.post(
                            f"{server.make_url(webhook.TWO_PAY_API_WEBHOOK_PATH)}",
                            data=body,
                            headers={
                                "Content-Type": "application/json",
                                "X-2PAY-Event": "referral_activated",
                                "X-2PAY-Timestamp": timestamp,
                                "X-2PAY-Signature": f"sha256={signature}",
                            },
                        )
                        self.assertEqual(response.status, 200)
                        self.assertEqual(
                            await response.json(),
                            {
                                "ok": True,
                                "delivered": True,
                                "already_delivered": False,
                            },
                        )
        finally:
            webhook.TWO_PAY_API_WEBHOOK_TOKEN = original_token

        event = delivery.await_args.args[1]
        self.assertEqual(event.recipient_telegram_id, 987654321)

    async def test_duplicate_payment_event_sends_only_once(self) -> None:
        class FakeBot:
            def __init__(self) -> None:
                self.messages: list[int] = []

            async def send_message(self, chat_id: int, _text: str, **_kwargs):
                self.messages.append(chat_id)
                return SimpleNamespace(message_id=42)

        original_token = webhook.TWO_PAY_API_WEBHOOK_TOKEN
        webhook.TWO_PAY_API_WEBHOOK_TOKEN = "shared-secret"
        body = json.dumps(
            {
                "event": "payment.code.v1",
                "payload": {
                    "transaction_id": "robokassa:42",
                    "recipient_telegram_id": 123456789,
                    "code": "AAAA-BBBB-CCCC-DDDD",
                    "region": "tr",
                    "nominal": 100,
                    "amount_rub": 400,
                },
            },
            separators=(",", ":"),
        ).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            b"shared-secret",
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-2PAY-Timestamp": timestamp,
            "X-2PAY-Signature": f"sha256={signature}",
        }
        bot = FakeBot()
        try:
            async with TestServer(
                webhook.build_app(bot, self.repository)
            ) as server, ClientSession() as session:
                first = await session.post(
                    f"{server.make_url(webhook.TWO_PAY_API_WEBHOOK_PATH)}",
                    data=body,
                    headers=headers,
                )
                second = await session.post(
                    f"{server.make_url(webhook.TWO_PAY_API_WEBHOOK_PATH)}",
                    data=body,
                    headers=headers,
                )
                self.assertEqual(first.status, 200)
                self.assertEqual(second.status, 200)
                self.assertFalse((await first.json())["already_delivered"])
                self.assertTrue((await second.json())["already_delivered"])
        finally:
            webhook.TWO_PAY_API_WEBHOOK_TOKEN = original_token

        self.assertEqual(bot.messages, [123456789])


if __name__ == "__main__":
    unittest.main()
