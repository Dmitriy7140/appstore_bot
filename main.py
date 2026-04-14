import asyncio
from aiogram import Bot, Dispatcher
from config.config_env import BOT_TOKEN

from menus import service_menu, start, amounts_menu, payment_menu, faqs


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(start.rt)
    dp.include_router(service_menu.rt)
    dp.include_router(amounts_menu.rt)
    dp.include_router(payment_menu.rt)
    dp.include_router(faqs.rt)
    print("Бот запущен")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
