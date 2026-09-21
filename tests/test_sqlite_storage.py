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
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        self.assertEqual(
            tables,
            {
                "fsm_states",
                "scheduled_announcements",
                "announcement_posts",
                "telegram_file_cache",
                "api_payment_deliveries",
                "api_referral_reward_deliveries",
                "api_notification_deliveries",
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
        await self.repository.close()

        self.repository = SQLiteRepository(self.path)
        await self.repository.open()
        self.assertEqual(
            (await self.repository.get_schedule(schedule["id"]))["send_time"], time(10, 30)
        )
        await self.repository.record_schedule_delivery(schedule["id"], 10, 1)
        self.assertEqual((await self.repository.get_schedule(schedule["id"]))["last_success"], 10)

        await self.repository.put_file_id("1:img/a.jpg", "telegram-file", "photo")
        self.assertEqual(
            await self.repository.get_file_id("1:img/a.jpg"), "telegram-file"
        )
        await self.repository.set_flag("broke", True)
        self.assertTrue(await self.repository.get_flag("broke"))

    async def test_multiple_posts_at_same_time_are_independent_and_survive_restart(self):
        values = dict(
            weekday=5, send_time=time(14, 10), audience="all",
            source_chat_id=123, source_message_id=17, created_by=123,
        )
        first = await self.repository.put_schedule(**values, post_preview="Первый пост")
        second = await self.repository.put_schedule(**values, post_preview="Второй пост")
        self.assertNotEqual(first["id"], second["id"])
        await self.repository.close()
        await self.repository.open()
        self.assertEqual(len(await self.repository.list_schedules(5)), 2)
        self.assertEqual(await self.repository.list_schedules(4), [])

        values["send_time"] = time(15, 10)
        await self.repository.put_schedule(**values, schedule_id=first["id"], post_preview="Изменённый")
        await self.repository.record_schedule_delivery(first["id"], 3, 1)
        self.assertEqual(await self.repository.get_schedule(second["id"]), second)
        posts = await self.repository.list_schedules(5)
        self.assertEqual([post["id"] for post in posts], [second["id"], first["id"]])
        self.assertEqual(posts[1]["last_success"], 3)
        self.assertTrue(await self.repository.delete_schedule(first["id"]))
        self.assertEqual(await self.repository.list_schedules(5), [second])
        with self.assertRaises(LookupError):
            await self.repository.put_schedule(**values, schedule_id=first["id"])
        third = await self.repository.put_schedule(**values)
        self.assertGreater(third["id"], first["id"])

    async def test_legacy_weekday_schema_migrates_without_losing_history(self):
        await self.repository.close()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript("""
                DROP TABLE scheduled_announcements;
                CREATE TABLE scheduled_announcements (
                    weekday INTEGER PRIMARY KEY CHECK (weekday BETWEEN 0 AND 6),
                    send_time TEXT NOT NULL, audience TEXT NOT NULL,
                    source_chat_id INTEGER NOT NULL, source_message_id INTEGER NOT NULL,
                    created_by INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_sent_at TEXT, last_success INTEGER, last_failed INTEGER
                );
                INSERT INTO scheduled_announcements VALUES (
                    5, '14:10:00', 'paid', 123, 17, 123, 1,
                    '2026-09-01', '2026-09-02', '2026-09-02', 100, 2
                );
                INSERT INTO scheduled_announcements VALUES (
                    6, '10:00:00', 'all', 123, 18, 123, 0,
                    '2026-09-01', '2026-09-02', NULL, NULL, NULL
                );
                PRAGMA user_version = 1;
            """)
        await self.repository.open()
        posts = await self.repository.list_schedules()
        self.assertEqual(len(posts), 1)
        first = posts[0]
        self.assertEqual(first["weekday"], 5)
        self.assertEqual(first["send_time"], time(14, 10))
        self.assertEqual(first["source_message_id"], 17)
        self.assertEqual(first["post_preview"], "")
        self.assertEqual((first["last_success"], first["last_failed"]), (100, 2))
        self.assertEqual(first["last_sent_at"], "2026-09-02")
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(connection.execute(
                "SELECT created_at, updated_at FROM scheduled_announcements WHERE id = ?",
                (first["id"],),
            ).fetchone(), ("2026-09-01", "2026-09-02"))
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM scheduled_announcements WHERE enabled = 0"
            ).fetchone()[0], 1)
        await self.repository.close()
        await self.repository.open()
        self.assertEqual(await self.repository.list_schedules(), posts)
        await self.repository.put_schedule(
            weekday=5, send_time=time(15, 10), audience="all",
            source_chat_id=123, source_message_id=19, created_by=123,
        )
        self.assertEqual(len(await self.repository.list_schedules(5)), 2)

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
