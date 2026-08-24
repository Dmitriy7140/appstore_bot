from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config.utils import IsAdmin, logger
from services.daily_sales_report import build_daily_sales_report
from services.two_pay_api_client import TwoPayApiError


router = Router()


@router.message(Command("salesreport"), IsAdmin())
async def show_daily_sales_report(message: Message) -> None:
    """Let administrators preview the latest completed sales report on demand."""
    try:
        report = await build_daily_sales_report()
    except TwoPayApiError:
        logger.exception("Could not read 2PAY daily sales")
        await message.answer(
            "❌ Не удалось получить сводку продаж из API. Проверьте журнал бота."
        )
        return
    await message.answer(report, parse_mode="HTML")
