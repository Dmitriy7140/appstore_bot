import asyncio
from aiogram import Bot, Dispatcher
from config.config_env import BOT_TOKEN
from config.utils import logger

from menus import service_menu, start, amounts_menu, payment_menu, faqs
from repository.database import database


bot = Bot(token=BOT_TOKEN)


async def main():
    # 1. сначала инфраструктура
    await database.init_db()

    # 2. потом всё остальное
    dp = Dispatcher()

    dp.message.middleware(database.UserMiddleware())
    dp.callback_query.middleware(database.UserMiddleware())

    dp.include_router(start.rt)
    dp.include_router(service_menu.rt)
    dp.include_router(amounts_menu.rt)
    dp.include_router(payment_menu.rt)
    dp.include_router(faqs.rt)

    logger.info("БД подключена, запускаем бота...")

    # 3. запуск
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())