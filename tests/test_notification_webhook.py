import asyncio
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from repository.sqlite_storage import SQLiteRepository
from services import two_pay_api_webhook as webhook


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_survives_restart_and_rejects_conflicting_replay(self):
        messages = []
        class Bot:
            async def send_message(self, chat_id, text, **kwargs):
                messages.append((chat_id, text))
                return SimpleNamespace(message_id=42)
        with tempfile.TemporaryDirectory() as temp, patch.object(webhook, 'TWO_PAY_API_WEBHOOK_TOKEN', 'secret'):
            path = Path(temp) / 'receipts.sqlite'
            for iteration in range(2):
                repo = SQLiteRepository(path)
                await repo.open()
                async with TestServer(webhook.build_app(Bot(), repo)) as server, ClientSession() as session:
                    async def post(text):
                        body = json.dumps({'event': 'telegram.html.once.v1', 'payload': {
                            'delivery_id': 'storefront:1066:code:1', 'chat_id': -123, 'text': text}}).encode()
                        stamp = str(int(time.time()))
                        signature = hmac.new(b'secret', stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
                        return await session.post(server.make_url(webhook.TWO_PAY_API_WEBHOOK_PATH), data=body,
                            headers={'X-2PAY-Timestamp': stamp, 'X-2PAY-Signature': 'sha256=' + signature})
                    response = await post('Оплата App Store (сайт)')
                    self.assertEqual(response.status, 200)
                    self.assertEqual((await response.json())['already_delivered'], bool(iteration))
                    self.assertEqual((await post('conflicting text')).status, 409)
                await repo.close()
            self.assertEqual(messages, [(-123, 'Оплата App Store (сайт)')])

    async def test_failed_send_can_retry_and_concurrent_delivery_is_rejected(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class Bot:
            failed = False
            async def send_message(self, *_args, **_kwargs):
                if not self.failed:
                    self.failed = True
                    raise RuntimeError('offline')
                entered.set()
                await release.wait()
                return SimpleNamespace(message_id=7)
        with tempfile.TemporaryDirectory() as temp:
            repo = SQLiteRepository(Path(temp) / 'receipts.sqlite')
            await repo.open()
            bot = Bot()
            payload = {'delivery_id': 'storefront:1:code:1', 'chat_id': -123, 'text': 'test'}
            with self.assertRaises(RuntimeError):
                await webhook._deliver_html_once(bot, repo, payload)
            task = asyncio.create_task(webhook._deliver_html_once(bot, repo, payload))
            await asyncio.wait_for(entered.wait(), 2)
            with self.assertRaises(webhook.DeliveryInProgressError):
                await webhook._deliver_html_once(bot, repo, payload)
            release.set()
            self.assertTrue((await task)['delivered'])
            self.assertTrue((await webhook._deliver_html_once(bot, repo, payload))['already_delivered'])
            await repo.close()
