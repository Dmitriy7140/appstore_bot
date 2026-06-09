import asyncio
from contextlib import suppress
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from config.config_env import BOT_TOKEN
from config.utils import logger
from services.tg_retry import RetryRequestMiddleware

from menus import service_menu, start, amounts_menu, payment_menu, faqs, referal_menu, confirm_payment_menu
from repository.database import database
from repository.sheets.anal_sheets import AnalSheets, anal_loop
from services.notification_service import Mailer
from services.scheduler import start_scheduler
from services.yookassa_webhook import start_webhook_server
from commands import announce, allusers

def _make_session() -> AiohttpSession:
    """
    Сессия Telegram, устойчивая к нестабильному каналу.

    На малонагруженном боте keep-alive соединения к api.telegram.org простаивают
    и закрываются Telegram/NAT'ом — а aiohttp пытается их переиспользовать и падает
    с ServerDisconnectedError. force_close=True заставляет открывать СВЕЖЕЕ соединение
    на каждый запрос: лишний TLS-handshake (для нашего трафика незаметно), зато
    протухших соединений в пуле не остаётся.
    """
    session = AiohttpSession()
    session._connector_init["force_close"] = True
    return session


bot = Bot(token=BOT_TOKEN, session=_make_session())
# повтор запросов к Telegram при сетевых обрывах канала
bot.session.middleware(RetryRequestMiddleware())


async def main():

    await database.init_db()

    anal_sheets = AnalSheets()
    anal_task = asyncio.create_task(anal_loop(anal_sheets))

    dp = Dispatcher()

    dp.message.middleware(database.UserMiddleware())
    dp.callback_query.middleware(database.UserMiddleware())

    dp.include_router(start.rt)
    dp.include_router(service_menu.rt)
    dp.include_router(amounts_menu.rt)
    dp.include_router(payment_menu.rt)
    dp.include_router(confirm_payment_menu.rt)
    dp.include_router(faqs.rt)
    dp.include_router(announce.router)
    dp.include_router(referal_menu.rt)
    dp.include_router(allusers.rt)
    mailer = Mailer(bot, logger)
    await mailer.start()

    dp["mailer"] = mailer
    scheduler = start_scheduler()

    logger.info("БД подключена, запускаем бота...")

    # 3. запуск

    # HTTP-сервер для уведомлений ЮKassa (подтверждение оплат)
    webhook_runner = await start_webhook_server(bot)

    # апдейты Telegram по-прежнему забираем поллингом
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        # aiogram сам ловит SIGTERM/SIGINT и корректно останавливает поллинг.
        # close_bot_session=False — сессию закроем сами, ПОСЛЕДНЕЙ, после остальной уборки.
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        # Детерминированный shutdown: гасим всё, что держит процесс, чтобы
        # systemctl stop/restart были мгновенными (а не ждали SIGKILL по таймауту).
        logger.info("Останавливаемся — гасим фоновые задачи и ресурсы...")

        # 1. перестаём принимать вебхуки ЮKassa
        with suppress(Exception):
            await webhook_runner.cleanup()

        # 2. фоновая аналитика
        anal_task.cancel()
        with suppress(asyncio.CancelledError):
            await anal_task

        # 3. воркеры рассылки
        with suppress(Exception):
            await mailer.stop()

        # 4. планировщик отчётов
        with suppress(Exception):
            scheduler.shutdown(wait=False)

        # 5. пул соединений БД
        with suppress(Exception):
            await database.close_pool()

        # 6. сессия бота — в самом конце
        with suppress(Exception):
            await bot.session.close()

        logger.info("Завершились чисто.")


if __name__ == "__main__":
    asyncio.run(main())