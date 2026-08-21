import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import time
from pathlib import Path

from aiogram.fsm.storage.base import StorageKey

from repository.sqlite_storage import (
    DeliveryPayloadConflictError,
    SQLiteFsmStorage,
    SQLiteRepository,
)


class SQLiteStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "bot.sqlite3"
        self.repository = SQLiteRepository(self.path)
        await self.repository.open()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp_dir.cleanup()

    async def test_schema_contains_only_the_agreed_local_groups(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(
            tables,
            {
                "fsm_states",
                "scheduled_announcements",
                "telegram_file_cache",
                "api_payment_deliveries",
                "api_referral_reward_deliveries",
                "service_flags",
            },
        )

    async def test_fsm_state_and_json_data_survive_reopen(self) -> None:
        key = StorageKey(bot_id=1, chat_id=2, user_id=3)
        storage = SQLiteFsmStorage(self.repository)
        await storage.set_state(key, "AnnounceState:waiting_time")
        await storage.set_data(key, {"weekday": 4, "send_time": "10:30"})
        await self.repository.close()

        self.repository = SQLiteRepository(self.path)
        await self.repository.open()
        storage = SQLiteFsmStorage(self.repository)
        self.assertEqual(await storage.get_state(key), "AnnounceState:waiting_time")
        self.assertEqual(
            await storage.get_data(key),
            {"weekday": 4, "send_time": "10:30"},
        )
        await storage.set_state(key, None)
        await storage.set_data(key, {})
        self.assertIsNone(await storage.get_state(key))
        self.assertEqual(await storage.get_data(key), {})

    async def test_schedule_media_and_flag(self) -> None:
        schedule = await self.repository.put_schedule(
            weekday=2,
            send_time=time(10, 30),
            audience="paid",
            source_chat_id=12931239,
            source_message_id=17,
            created_by=12931239,
        )
        self.assertEqual(schedule["send_time"], time(10, 30))
        await self.repository.record_schedule_delivery(2, 10, 1)
        self.assertEqual((await self.repository.get_schedule(2))["last_success"], 10)

        await self.repository.put_file_id("1:img/a.jpg", "telegram-file", "photo")
        self.assertEqual(
            await self.repository.get_file_id("1:img/a.jpg"), "telegram-file"
        )
        await self.repository.set_flag("broke", True)
        self.assertTrue(await self.repository.get_flag("broke"))

    async def test_payment_delivery_claim_is_idempotent_and_detects_conflict(self) -> None:
        claim = await self.repository.claim_payment_delivery("tx:1", "hash-1", 120)
        self.assertEqual(claim, "claimed")
        self.assertEqual(
            await self.repository.claim_payment_delivery("tx:1", "hash-1", 120),
            "in_progress",
        )
        await self.repository.complete_payment_delivery("tx:1", 99)
        self.assertEqual(
            await self.repository.claim_payment_delivery("tx:1", "hash-1", 120),
            "already_delivered",
        )
        with self.assertRaises(DeliveryPayloadConflictError):
            await self.repository.claim_payment_delivery("tx:1", "another-hash", 120)

    async def test_failed_referral_delivery_can_be_retried(self) -> None:
        args = ("550e8400-e29b-41d4-a716-446655440000", "tx:2", "hash-2", 120)
        self.assertEqual(
            await self.repository.claim_referral_reward_delivery(*args), "claimed"
        )
        await self.repository.fail_referral_reward_delivery(args[0], "network")
        self.assertEqual(
            await self.repository.claim_referral_reward_delivery(*args), "claimed"
        )
