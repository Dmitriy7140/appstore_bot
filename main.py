import asyncio
from aiogram import Bot, Dispatcher
from config.config_env import BOT_TOKEN
from config.utils import logger

from menus import service_menu, start, amounts_menu, payment_menu, faqs, referal_menu
from repository.database import database
from repository.sheets.anal_sheets import AnalSheets, anal_loop
from services.notification_service import Mailer
from commands import announce

bot = Bot(token=BOT_TOKEN)


async def main():

    await database.init_db()
    anal_sheets = AnalSheets()
    asyncio.create_task(anal_loop(anal_sheets))

    dp = Dispatcher()

    dp.message.middleware(database.UserMiddleware())
    dp.callback_query.middleware(database.UserMiddleware())

    dp.include_router(start.rt)
    dp.include_router(service_menu.rt)
    dp.include_router(amounts_menu.rt)
    dp.include_router(payment_menu.rt)
    dp.include_router(faqs.rt)
    dp.include_router(announce.router)
    dp.include_router(referal_menu.rt)
    mailer = Mailer(bot, logger)
    await mailer.start()

    dp["mailer"] = mailer

    logger.info("БД подключена, запускаем бота...")

    # 3. запуск
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())