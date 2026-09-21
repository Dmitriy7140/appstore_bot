import asyncio
import logging
import tempfile
import unittest
from contextlib import suppress
from datetime import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import CopyMessage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from commands import announce
from commands.announcement_builder import finish_buttons
from commands.announce import (
    delivery_keyboard, has_time_conflict, parse_time, recommended_time,
    time_keyboard, weekdays_keyboard,
)
from repository.sqlite_storage import SQLiteRepository
from services.notification_service import Mailer
from services.scheduler import (
    WEEKDAY_CRON, _send_scheduled_announcement, announcement_job_id,
    schedule_announcement_job,
)


class AnnouncementHelpersTest(unittest.TestCase):
    def test_parse_time_accepts_strict_24_hour_format(self):
        self.assertEqual(parse_time("09:30").strftime("%H:%M"), "09:30")
        self.assertIsNone(parse_time("9:30"))
        self.assertIsNone(parse_time("24:00"))
        self.assertIsNone(parse_time("12:60"))

    def test_delivery_and_weekday_keyboards(self):
        self.assertEqual(len(delivery_keyboard().inline_keyboard), 2)
        keyboard = weekdays_keyboard([]).inline_keyboard
        self.assertEqual(len(keyboard), 8)
        self.assertEqual(keyboard[5][0].text, "Суббота")
        self.assertEqual(keyboard[6][0].text, "Воскресенье")
        self.assertEqual(
            WEEKDAY_CRON,
            ("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
        )

    def test_sunday_is_registered_as_sunday_cron_job(self):
        class SchedulerStub:
            def add_job(self, _function, **kwargs):
                self.kwargs = kwargs

        scheduler = SchedulerStub()
        schedule_announcement_job(
            scheduler,
            object(),
            {"id": 12, "weekday": 6, "send_time": time(14, 25)},
        )

        self.assertEqual(scheduler.kwargs["day_of_week"], "sun")
        self.assertEqual(scheduler.kwargs["hour"], 14)
        self.assertEqual(scheduler.kwargs["minute"], 25)
        self.assertNotIn("end_date", scheduler.kwargs)

    def test_recommendation_reserves_hour_and_checks_neighbouring_days(self):
        posts = [{"weekday": 5, "send_time": time(14, 10)}]
        self.assertEqual(recommended_time(5, posts), time(15, 10))
        self.assertTrue(has_time_conflict(5, time(14, 50), posts))
        self.assertFalse(has_time_conflict(5, time(15, 10), posts))
        self.assertTrue(has_time_conflict(5, time(14, 10), posts))
        self.assertTrue(has_time_conflict(0, time(0, 10), [
            {"weekday": 6, "send_time": time(23, 40)},
        ]))
        self.assertTrue(has_time_conflict(6, time(23, 50), [
            {"weekday": 0, "send_time": time(0, 20)},
        ]))
        # A manually entered time is rounded up, retaining the full hour gap.
        self.assertEqual(recommended_time(5, [
            {"weekday": 5, "send_time": time(14, 17)},
        ]), time(15, 20))

    def test_time_pagination_covers_day_and_marks_conflicts(self):
        posts = [{"weekday": 5, "send_time": time(14, 10)}]
        choices = {}
        for page in range(announce.TIME_PAGE_COUNT):
            rows = time_keyboard(5, posts, page).inline_keyboard
            buttons = [button for row in rows for button in row]
            for button in buttons:
                if button.callback_data.startswith("announce_time:"):
                    value = button.callback_data.split(":", 1)[1]
                    self.assertNotIn(value, choices)
                    choices[value] = button.text
            callbacks = {button.callback_data for button in buttons}
            self.assertNotIn("announce_time_page:-1", callbacks)
            self.assertNotIn("announce_time_page:6", callbacks)
        self.assertEqual(len(choices), 144)
        self.assertIn("00:00", choices)
        self.assertIn("23:50", choices)
        self.assertEqual(choices["14:40"], "⏳ 14:40")
        self.assertEqual(choices["15:10"], "✅ 15:10")

    def test_media_caption_and_plain_text_previews(self):
        message = SimpleNamespace(text=None, caption="Купите\n наши носки", content_type="photo")
        self.assertEqual(announce.post_preview(message), "Купите наши носки")
        message.caption = None
        self.assertEqual(announce.post_preview(message), "Фото без подписи")
        message.text = "я" * 1000
        self.assertLessEqual(len(announce.post_preview(message)), 80)


class AnnouncementFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteRepository(Path(self.temp_dir.name) / "bot.sqlite3")
        await self.repository.open()
        self.state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=2, user_id=3))
        self.callback = SimpleNamespace(
            data="", message=AsyncMock(), from_user=SimpleNamespace(id=3), answer=AsyncMock(),
            bot=SimpleNamespace(copy_message=AsyncMock(return_value=SimpleNamespace(message_id=900))),
        )
        self.scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
        self.repo_patch = patch("commands.announce.get_repository", return_value=self.repository)
        self.repo_patch.start()

    async def asyncTearDown(self):
        self.repo_patch.stop()
        await self.state.storage.close()
        await self.repository.close()
        self.temp_dir.cleanup()

    async def add_post(self, send_time=time(14, 10), source_message_id=20):
        return await self.repository.put_schedule(
            weekday=5, send_time=send_time, audience="all", source_chat_id=2,
            source_message_id=source_message_id, created_by=3, post_preview="Купите наши носки",
        )

    async def test_add_second_post_through_day_time_and_confirmation(self):
        first = await self.add_post()
        await self.state.set_data({"delivery_mode": "scheduled"})
        self.callback.data = "announce_weekday:5"
        await announce.choose_weekday(self.callback, self.state)
        text = self.callback.message.edit_text.call_args.args[0]
        self.assertIn("В субботу уже есть рассылка:", text)
        self.assertIn("14:10 — пост «Купите наши носки»", text)
        self.assertIn("Добавить ещё?", text)

        self.callback.data = "announce_add:5"
        await announce.add_scheduled_post(self.callback, self.state)
        self.assertEqual(await self.state.get_state(), announce.AnnounceState.waiting_time.state)
        self.assertIn("Рекомендуем: 15:10", self.callback.message.edit_text.call_args.args[0])
        self.callback.data = "announce_time_page:4"
        await announce.paginate_times(self.callback, self.state)
        self.assertIsNone((await self.state.get_data())["send_time"])

        self.callback.data = "announce_time:14:40"
        await announce.choose_time(self.callback, self.state)
        self.assertIn("встанет в очередь", self.callback.message.answer.call_args.args[0])
        self.assertEqual((await self.state.get_data())["send_time"], "14:40")
        message = SimpleNamespace(
            text="Новый пост", caption=None, chat=SimpleNamespace(id=2),
            message_id=21, answer=AsyncMock(), reply_markup=None,
        )
        await announce.announce_get_message(message, self.state)
        await finish_buttons(self.callback, self.state)
        self.callback.data = "announce_all"
        await announce.announce_get_audience(self.callback, self.state)
        await announce.announce_confirm(self.callback, self.state, object(), self.scheduler)
        posts = await self.repository.list_schedules(5)
        self.assertEqual(posts[0], first)
        self.assertEqual(posts[1]["send_time"], time(14, 40))
        self.assertEqual(posts[1]["post_preview"], "Новый пост")
        self.assertIsNone(await self.state.get_state())

    async def test_edit_and_delete_affect_only_selected_post_and_job(self):
        first = await self.add_post()
        second = await self.add_post(time(15, 10), 21)
        for post in (first, second):
            schedule_announcement_job(self.scheduler, object(), post)
        self.assertEqual(len(self.scheduler.get_jobs()), 2)
        self.callback.data = f"announce_edit_post:{first['id']}"
        await self.state.set_data({"delivery_mode": "scheduled"})
        await announce.change_scheduled_day(self.callback, self.state)
        await self.state.update_data(
            send_time="12:00", source_chat_id=2, source_message_id=22,
            audience="paid", post_preview="Изменённый пост",
        )
        await announce.announce_get_message(SimpleNamespace(
            text="Изменённый пост", caption=None, chat=SimpleNamespace(id=2),
            message_id=22, answer=AsyncMock(), reply_markup=None,
        ), self.state)
        await finish_buttons(self.callback, self.state)
        self.callback.data = "announce_paid"
        await announce.announce_get_audience(self.callback, self.state)
        # Start paused so replace_existing is applied by the real job store.
        self.scheduler.start(paused=True)
        try:
            await announce.announce_confirm(self.callback, self.state, object(), self.scheduler)
            self.assertEqual(len(self.scheduler.get_jobs()), 2)
            self.assertEqual(await self.repository.get_schedule(second["id"]), second)
            self.assertEqual((await self.repository.get_schedule(first["id"]))["send_time"], time(12))
            self.callback.data = f"announce_delete_post:{first['id']}"
            await announce.delete_scheduled_day(self.callback, self.state, self.scheduler)
            self.assertEqual(await self.repository.list_schedules(5), [second])
            self.assertIsNone(self.scheduler.get_job(announcement_job_id(first["id"])))
            self.assertIsNotNone(self.scheduler.get_job(announcement_job_id(second["id"])))
        finally:
            self.scheduler.shutdown(wait=False)

    async def test_manual_time_and_back_button(self):
        await self.state.set_data({"weekday": 5, "schedule_id": None})
        message = SimpleNamespace(text="14:17", answer=AsyncMock())
        await announce.announce_get_time(message, self.state)
        self.assertEqual((await self.state.get_data())["send_time"], "14:17")
        # Exercise registered filters: the back button must return to weekdays.
        self.callback.data = "announce_back_to_days"
        for handler in announce.router.callback_query.handlers:
            with patch("config.utils.ADMIN_IDS", [3]):
                matched, _ = await handler.check(
                    self.callback, raw_state=announce.AnnounceState.waiting_time.state,
                )
            if matched:
                await handler.callback(self.callback, self.state)
                break
        else:
            self.fail("Back button has no matching handler")
        self.assertEqual(await self.state.get_state(), announce.AnnounceState.choosing_day.state)
        self.assertIsNone((await self.state.get_data())["schedule_id"])

    async def test_old_weekday_delete_button_cannot_delete_post_with_same_id(self):
        post = await self.add_post()
        self.callback.data = f"announce_delete:{post['id']}"
        for handler in announce.router.callback_query.handlers:
            with patch("config.utils.ADMIN_IDS", [3]):
                matched, _ = await handler.check(
                    self.callback, raw_state=announce.AnnounceState.choosing_day.state,
                )
            if matched:
                await handler.callback(self.callback, self.state)
                break
        else:
            self.fail("Legacy button has no matching handler")
        self.assertEqual(await self.repository.list_schedules(5), [post])

    async def test_scheduled_jobs_use_own_post_and_record_results(self):
        first = await self.add_post()
        second = await self.add_post(time(14, 10), 21)
        copied = []

        async def copy_message(**kwargs):
            copied.append(kwargs["message_id"])

        mailer = Mailer(SimpleNamespace(copy_message=copy_message), logging.getLogger(__name__), rate=10000)
        await mailer.start()
        try:
            with (
                patch("services.scheduler.get_repository", return_value=self.repository),
                patch("services.scheduler.TEST_MODE", False),
                patch("services.scheduler.get_audience", AsyncMock(return_value=[10, 11])),
            ):
                await asyncio.gather(
                    _send_scheduled_announcement(first["id"], mailer),
                    _send_scheduled_announcement(second["id"], mailer),
                )
        finally:
            await mailer.stop()
        self.assertEqual(copied, [20, 20, 21, 21])
        for post in await self.repository.list_schedules(5):
            self.assertEqual(post["last_success"], 2)

    async def test_deleted_queued_post_is_skipped_without_sending(self):
        post = await self.add_post()
        mailer = Mock()

        async def send_copy(loader, *_args):
            await self.repository.delete_schedule(post["id"])
            self.assertEqual(await loader(), [])
            return 0, 0

        mailer.send_copy_to_many = send_copy
        with (
            patch("services.scheduler.get_repository", return_value=self.repository),
            patch("services.scheduler.get_audience", AsyncMock()) as audience,
            patch.object(self.repository, "record_schedule_delivery", AsyncMock()) as record,
        ):
            await _send_scheduled_announcement(post["id"], mailer)
        audience.assert_not_awaited()
        record.assert_not_awaited()


class _FakeBot:
    async def copy_message(self, **kwargs):
        await asyncio.sleep(0)


class MailerTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_and_failed_recipient_finish_before_next_post(self):
        retry_started = asyncio.Event()
        attempted_retry = False
        delivered = []

        async def copy_message(**kwargs):
            nonlocal attempted_retry
            if kwargs["message_id"] == 20:
                if kwargs["chat_id"] == 2:
                    raise TelegramForbiddenError(method=CopyMessage(**kwargs), message="Blocked")
                if not attempted_retry:
                    attempted_retry = True
                    retry_started.set()
                    raise TelegramRetryAfter(method=CopyMessage(**kwargs), message="Wait", retry_after=0)
            delivered.append(kwargs["message_id"])

        mailer = Mailer(SimpleNamespace(copy_message=copy_message), logging.getLogger(__name__), rate=10000)
        await mailer.start()
        first = asyncio.create_task(mailer.send_copy_to_many([1, 2], 10, 20))
        second = None
        try:
            await asyncio.wait_for(retry_started.wait(), 1)
            second = asyncio.create_task(mailer.send_copy_to_many([1], 10, 21))
            self.assertEqual(await asyncio.wait_for(first, 2), (1, 1))
            self.assertEqual(await asyncio.wait_for(second, 1), (1, 0))
            self.assertEqual(delivered, [20, 21])
        finally:
            tasks = [task for task in (first, second) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await mailer.stop()

    async def test_next_post_waits_for_slow_last_recipient_even_if_caller_cancelled(self):
        for cancel_caller in (False, True):
            with self.subTest(cancel_caller=cancel_caller):
                slow_started = asyncio.Event()
                release_slow = asyncio.Event()
                fast_finished = asyncio.Event()
                delivered = []

                async def copy_message(*, chat_id, from_chat_id, message_id):
                    if message_id == 20 and chat_id == 1:
                        slow_started.set()
                        await release_slow.wait()
                    delivered.append((message_id, chat_id))
                    if message_id == 20 and chat_id == 2:
                        fast_finished.set()

                mailer = Mailer(
                    SimpleNamespace(copy_message=copy_message),
                    logging.getLogger(__name__), workers=2, rate=10000,
                )
                await mailer.start()
                first = asyncio.create_task(mailer.send_copy_to_many([1, 2], 10, 20))
                tasks = [first]
                try:
                    await asyncio.wait_for(slow_started.wait(), 1)
                    await asyncio.wait_for(fast_finished.wait(), 1)
                    if cancel_caller:
                        first.cancel()
                        with suppress(asyncio.CancelledError):
                            await first
                    loader = AsyncMock(return_value=[1])
                    second = asyncio.create_task(mailer.send_copy_to_many(loader, 10, 21))
                    third = asyncio.create_task(mailer.send_copy_to_many([1], 10, 22))
                    tasks.extend([second, third])
                    await asyncio.sleep(0.03)
                    loader.assert_not_awaited()
                    self.assertEqual(delivered, [(20, 2)])
                    self.assertFalse(second.done())
                    release_slow.set()
                    self.assertEqual(await asyncio.wait_for(second, 1), (1, 0))
                    self.assertEqual(await asyncio.wait_for(third, 1), (1, 0))
                    if not cancel_caller:
                        self.assertEqual(await first, (2, 0))
                    self.assertEqual(delivered, [(20, 2), (20, 1), (21, 1), (22, 1)])
                finally:
                    release_slow.set()
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await mailer.stop()

    async def test_failed_audience_loader_does_not_block_queue(self):
        mailer = Mailer(_FakeBot(), logging.getLogger(__name__), workers=2, rate=10000)
        await mailer.start()
        try:
            with self.assertRaises(RuntimeError):
                await mailer.send_copy_to_many(AsyncMock(side_effect=RuntimeError("API down")), 10, 20)
            self.assertEqual(await mailer.send_copy_to_many([], 10, 20), (0, 0))
            self.assertEqual(await asyncio.wait_for(mailer.send_copy_to_many([1], 10, 21), 1), (1, 0))
        finally:
            await mailer.stop()

    async def test_concurrent_batches_keep_separate_results(self):
        mailer = Mailer(_FakeBot(), logging.getLogger(__name__), workers=2, rate=1000)
        await mailer.start()
        try:
            first, second = await asyncio.gather(
                mailer.send_copy_to_many([1, 2], 10, 20),
                mailer.send_copy_to_many([3], 10, 20),
            )
        finally:
            await mailer.stop()

        self.assertEqual(first, (2, 0))
        self.assertEqual(second, (1, 0))


if __name__ == "__main__":
    unittest.main()
