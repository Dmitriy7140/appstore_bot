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
from services.daily_sales_report import (
    build_daily_sales_report,
    latest_closed_period_end_date,
)
from services.notification_service import Mailer
from services.announcement_posts import post_markup
from services.tg_retry import send_flood_safe
from services.two_pay_api_client import get_audience, sync_daily_marketing_sales

from config.utils import logger


WEEKDAY_CRON = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAILY_SALES_REPORT_JOB_ID = "daily_sales_report"


def announcement_job_id(schedule_id: int) -> str:
    return f"scheduled_announcement_{schedule_id}"


async def _send_daily_sales_report(mailer: Mailer) -> None:
    if DAILY_SALES_REPORT_CHAT_ID is None:
        return
    period_end_date = latest_closed_period_end_date()
    try:
        marketing_sales = await sync_daily_marketing_sales(period_end_date)
    except Exception:
        logger.exception("Could not sync daily sales to the marketing spreadsheet")
    else:
        logger.info(
            "Daily marketing report synced: date=%s row=%s sales=%s amount_rub=%s",
            marketing_sales.report_date,
            marketing_sales.marketing_sheet_row,
            marketing_sales.sales_count,
            marketing_sales.sales_rub,
        )
    try:
        report = await build_daily_sales_report(period_end_date)
        await send_flood_safe(
            lambda: mailer.bot.send_message(
                DAILY_SALES_REPORT_CHAT_ID,
                report,
                parse_mode=ParseMode.HTML,
            )
        )
    except Exception:
        logger.exception("Could not send daily site/TMA sales report")
        return
    logger.info("Daily site/TMA sales report sent to chat=%s", DAILY_SALES_REPORT_CHAT_ID)


async def _send_scheduled_announcement(schedule_id: int, mailer: Mailer) -> None:
    announcement = await get_repository().get_schedule(schedule_id)
    if announcement is None:
        logger.info("Scheduled announcement id=%s no longer exists", schedule_id)
        return

    skipped = False
    copy_options = {}
    if announcement["post_id"] is not None:
        post = await get_repository().get_announcement_post(announcement["post_id"])
        if post is None:
            raise RuntimeError("Scheduled announcement post is missing")
        copy_options["reply_markup"] = post_markup(post)

    async def load_audience():
        nonlocal skipped
        # Resolve recipients only when this post reaches the front of the queue.
        # Deleted posts waiting behind a long broadcast must not be sent.
        current = await get_repository().get_schedule(schedule_id)
        if current is None or any(
            current[key] != announcement[key]
            for key in ("weekday", "send_time", "audience", "source_chat_id", "source_message_id", "post_id")
        ):
            skipped = True
            return []
        return ADMIN_IDS if TEST_MODE else await get_audience(announcement["audience"])

    success, failed = await mailer.send_copy_to_many(
        load_audience,
        announcement["source_chat_id"],
        announcement["source_message_id"],
        **copy_options,
    )
    if skipped:
        logger.info("Skipped deleted or changed queued announcement id=%s", schedule_id)
        return
    await get_repository().record_schedule_delivery(schedule_id, success, failed)
    logger.info(
        "Scheduled announcement sent: id=%s audience=%s total=%s success=%s failed=%s",
        schedule_id,
        announcement["audience"],
        success + failed,
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
        id=announcement_job_id(announcement["id"]),
        replace_existing=True,
        day_of_week=WEEKDAY_CRON[weekday],
        hour=send_time.hour,
        minute=send_time.minute,
        args=(announcement["id"], mailer),
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )


def remove_announcement_job(scheduler: AsyncIOScheduler, schedule_id: int) -> None:
    job = scheduler.get_job(announcement_job_id(schedule_id))
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
        logger.info("Daily site/TMA sales report is disabled")
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
