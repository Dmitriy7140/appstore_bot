from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.enums import ParseMode
import pytz
from config.config_env import (
    ADMIN_IDS,
    DAILY_SALES_REPORT_CHAT_ID,
    DAILY_SALES_REPORT_HOUR,
    DAILY_SALES_REPORT_MINUTE,
    TEST_MODE,
)
from repository.sqlite_storage import get_repository
from services.daily_sales_report import build_daily_sales_report
from services.notification_service import Mailer
from services.tg_retry import send_flood_safe
from services.two_pay_api_client import get_audience

from config.utils import logger


WEEKDAY_CRON = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAILY_SALES_REPORT_JOB_ID = "daily_sales_report"


def announcement_job_id(weekday: int) -> str:
    return f"scheduled_announcement_{weekday}"


async def _send_daily_sales_report(mailer: Mailer) -> None:
    if DAILY_SALES_REPORT_CHAT_ID is None:
        return
    try:
        report = await build_daily_sales_report()
        await send_flood_safe(
            lambda: mailer.bot.send_message(
                DAILY_SALES_REPORT_CHAT_ID,
                report,
                parse_mode=ParseMode.HTML,
            )
        )
    except Exception:
        logger.exception("Could not send daily website-sales report")
        return
    logger.info("Daily website-sales report sent to chat=%s", DAILY_SALES_REPORT_CHAT_ID)


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

    if DAILY_SALES_REPORT_CHAT_ID is None:
        logger.info("Daily website-sales report is disabled")
    else:
        scheduler.add_job(
            _send_daily_sales_report,
            trigger="cron",
            id=DAILY_SALES_REPORT_JOB_ID,
            replace_existing=True,
            hour=DAILY_SALES_REPORT_HOUR,
            minute=DAILY_SALES_REPORT_MINUTE,
            args=(mailer,),
            coalesce=True,
            max_instances=1,
            misfire_grace_time=600,
        )

    scheduler.start()

    logger.info("Scheduler запущен")

    return scheduler
