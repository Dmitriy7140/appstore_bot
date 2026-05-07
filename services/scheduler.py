from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from repository.sheets.sales_report import MarketingReportService

from config.utils import logger
def start_scheduler():

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
        hour=0,
        minute=5
    )

    scheduler.start()

    logger.info("Scheduler запущен")

    return scheduler
