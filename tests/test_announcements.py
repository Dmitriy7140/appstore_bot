import asyncio
import logging
import unittest
from datetime import time

from commands.announce import delivery_keyboard, parse_time, weekdays_keyboard
from services.notification_service import Mailer
from services.scheduler import WEEKDAY_CRON, schedule_announcement_job


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
            {"weekday": 6, "send_time": time(14, 25)},
        )

        self.assertEqual(scheduler.kwargs["day_of_week"], "sun")
        self.assertEqual(scheduler.kwargs["hour"], 14)
        self.assertEqual(scheduler.kwargs["minute"], 25)
        self.assertNotIn("end_date", scheduler.kwargs)


class _FakeBot:
    async def copy_message(self, **kwargs):
        await asyncio.sleep(0)


class MailerTest(unittest.IsolatedAsyncioTestCase):
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
