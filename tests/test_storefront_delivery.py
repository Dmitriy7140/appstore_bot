import unittest
from unittest.mock import patch
from services.storefront_delivery import buyer_notification
from services.two_pay_api_webhook import WebhookInputError
from keyboards.webapp_buttons import mini_app_url

def payload(**changes):
    value = {"delivery_id": "storefront:42:buyer:" + "a" * 64, "invoice_id": 42,
             "recipient_telegram_id": 123, "code": "<gift&code>", "product_type": "psn_wallet_code",
             "region": "tr", "nominal": 250, "currency": "TRY"}
    value.update(changes)
    return value

class StorefrontDeliveryTests(unittest.TestCase):
    def test_private_buyer_message_and_escaped_code(self):
        message = buyer_notification(payload())
        self.assertEqual(message["chat_id"],123)
        self.assertIn("PlayStation", message["text"])
        self.assertIn("&lt;gift&amp;code&gt;", message["text"])

    def test_rejects_manager_recipient_and_mismatched_invoice(self):
        for value in [payload(recipient_telegram_id=-123),payload(invoice_id=43),payload(recipient_telegram_id=True)]:
            with self.assertRaises(WebhookInputError):
                buyer_notification(value)

    def test_configured_site_landing_preserves_query(self):
        with patch.dict("os.environ",{"TMA_APPSTORE_URL":"https://staging.example.com/appstore?campaign=bot"}):
            self.assertEqual(mini_app_url("appstore"),"https://staging.example.com/appstore?campaign=bot&s=appstore")


class StorefrontDeliveryHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_delivery_survives_restart_and_rejects_conflicting_replay(self):
        import hashlib, hmac, json, tempfile, time
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from aiohttp import ClientSession
        from aiohttp.test_utils import TestServer
        from repository.sqlite_storage import SQLiteRepository
        from services import two_pay_api_webhook as webhook
        bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)))
        with tempfile.TemporaryDirectory() as temp, patch.object(webhook,'TWO_PAY_API_WEBHOOK_TOKEN','secret'), patch.object(webhook,'STOREFRONT_DELIVERY_ENVIRONMENT','production'):
            for iteration in range(2):
                repo=SQLiteRepository(Path(temp)/'bot.sqlite')
                await repo.open()
                try:
                    async with TestServer(webhook.build_app(bot,repo)) as server, ClientSession() as session:
                        async def post(data,signed=True):
                            body=json.dumps({'event':'storefront.code.v1','payload':data}).encode()
                            stamp=str(int(time.time()))
                            sig=hmac.new(b'secret',stamp.encode()+b'.'+body,hashlib.sha256).hexdigest() if signed else '0'*64
                            return await session.post(server.make_url(webhook.TWO_PAY_API_WEBHOOK_PATH),data=body,
                                headers={'X-2PAY-Timestamp':stamp,'X-2PAY-Signature':'sha256='+sig})
                        self.assertEqual((await post(payload(),False)).status,401)
                        first=await post(payload())
                        self.assertEqual(first.status,200)
                        self.assertEqual((await first.json())['already_delivered'],bool(iteration))
                        self.assertEqual((await post(payload(code='different-code'))).status,409)
                finally:
                    await repo.close()
        self.assertEqual(bot.send_message.await_count,1)
        self.assertEqual(bot.send_message.call_args.args[0],123)


class DeliveryEnvironmentTests(unittest.TestCase):
    def test_staging_requires_an_explicit_environment_and_production_preserves_legacy_events(self):
        self.assertEqual(buyer_notification(payload())["chat_id"], 123)
        self.assertEqual(buyer_notification(payload(delivery_environment="staging"), expected_environment="staging")["chat_id"], 123)
        for body, expected in [(payload(), "staging"), (payload(delivery_environment="staging"), "production"),
                               (payload(delivery_environment="unknown"), "production")]:
            with self.assertRaises(WebhookInputError):
                buyer_notification(body, expected_environment=expected)


class DeliveryEnvironmentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_receiver_rejects_even_an_authenticated_event_before_sending(self):
        import hashlib, hmac, json, tempfile, time
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from aiohttp import ClientSession
        from aiohttp.test_utils import TestServer
        from repository.sqlite_storage import SQLiteRepository
        from services import two_pay_api_webhook as webhook
        for role, source in [("production", "staging"), ("staging", "production")]:
            bot = SimpleNamespace(send_message=AsyncMock())
            with tempfile.TemporaryDirectory() as temp, patch.object(webhook, "TWO_PAY_API_WEBHOOK_TOKEN", "secret"), patch.object(webhook, "STOREFRONT_DELIVERY_ENVIRONMENT", role):
                repo = SQLiteRepository(Path(temp)/"bot.sqlite")
                await repo.open()
                try:
                    async with TestServer(webhook.build_app(bot, repo)) as server, ClientSession() as session:
                        raw = json.dumps({"event": "storefront.code.v1", "payload": payload(delivery_environment=source)}).encode()
                        stamp = str(int(time.time()))
                        signature = hmac.new(b"secret", stamp.encode()+b"."+raw, hashlib.sha256).hexdigest()
                        response = await session.post(server.make_url(webhook.TWO_PAY_API_WEBHOOK_PATH), data=raw,
                            headers={"X-2PAY-Timestamp": stamp, "X-2PAY-Signature": "sha256="+signature})
                        self.assertEqual(response.status, 400)
                        bot.send_message.assert_not_awaited()
                finally:
                    await repo.close()
