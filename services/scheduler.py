from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from config.config_env import ADMIN_IDS, TEST_MODE
from repository.sqlite_storage import get_repository
from services.notification_service import Mailer
from services.two_pay_api_client import get_audience

from config.utils import logger


WEEKDAY_CRON = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def announcement_job_id(weekday: int) -> str:
    return f"scheduled_announcement_{weekday}"


async def _send_scheduled_announcement(weekday: int, mailer: Mailer) -> None:
    announcement = await get_repository().get_schedule(weekday)
    if announcement is None:
        logger.info("Scheduled announcement for weekday=%s no longer exists", weekday)
        return

    users = (
        ADMIN_IDS
        if TEST_MODE
        else await get_audience(announcement["audience"])
    )
    success, failed = await mailer.send_copy_to_many(
        users,
        announcement["source_chat_id"],
        announcement["source_message_id"],
    )
    await get_repository().record_schedule_delivery(weekday, success, failed)
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

    # Only the schedule is local. Recipient audiences still come from the API.
    for announcement in await get_repository().list_schedules():
        schedule_announcement_job(scheduler, mailer, announcement)

    scheduler.start()

    logger.info("Scheduler запущен")

    return scheduler
