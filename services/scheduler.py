from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from repository.sheets.sales_report import MarketingReportService
from repository.database.announcements import (
    get_scheduled_announcement,
    list_scheduled_announcements,
    mark_scheduled_announcement_sent,
)
from repository.database.database import get_user_ids_by_state
from config.config_env import ADMIN_IDS, TEST_MODE
from services.notification_service import Mailer

from config.utils import logger


WEEKDAY_CRON = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def announcement_job_id(weekday: int) -> str:
    return f"scheduled_announcement_{weekday}"


async def _send_scheduled_announcement(weekday: int, mailer: Mailer) -> None:
    announcement = await get_scheduled_announcement(weekday)
    if announcement is None:
        logger.info("Scheduled announcement for weekday=%s no longer exists", weekday)
        return

    users = (
        ADMIN_IDS
        if TEST_MODE
        else await get_user_ids_by_state(announcement["audience"])
    )
    success, failed = await mailer.send_copy_to_many(
        users,
        announcement["source_chat_id"],
        announcement["source_message_id"],
    )
    await mark_scheduled_announcement_sent(weekday, success, failed)
    logger.info(
        "Scheduled announcement sent: weekday=%s audience=%s total=%s success=%s failed=%s",
        weekday,
        announcement["audience"],
        len(users),
        success,
        failed,
    )


def schedule_announcement_job(
    scheduler: AsyncIOScheduler,
    mailer: Mailer,
    announcement: dict,
) -> None:
    weekday = announcement["weekday"]
    send_time = announcement["send_time"]
    scheduler.add_job(
        _send_scheduled_announcement,
        trigger="cron",
        id=announcement_job_id(weekday),
        replace_existing=True,
        day_of_week=WEEKDAY_CRON[weekday],
        hour=send_time.hour,
        minute=send_time.minute,
        args=(weekday, mailer),
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )


def remove_announcement_job(scheduler: AsyncIOScheduler, weekday: int) -> None:
    job = scheduler.get_job(announcement_job_id(weekday))
    if job is not None:
        scheduler.remove_job(job.id)


async def start_scheduler(mailer: Mailer):

    scheduler = AsyncIOScheduler(
        timezone=pytz.timezone("Europe/Moscow")
    )

    service = MarketingReportService()

    async def job():
        try:
            await service.write_daily_report()
            logger.info("Marketing report отправлен")
        except Exception as e:
            logger.exception(f"Scheduler error: {e}")

    scheduler.add_job(
        job,
        trigger="cron",
        hour=10,
        minute=00
    )

    for announcement in await list_scheduled_announcements():
        schedule_announcement_job(scheduler, mailer, announcement)

    scheduler.start()

    logger.info("Scheduler запущен")

    return scheduler
