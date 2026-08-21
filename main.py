import asyncio
import os

from contextlib import suppress
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import SimpleEventIsolation
from config.config_env import BOT_TOKEN, SQLITE_PATH
from config.utils import logger
from repository.sqlite_storage import (
    SQLiteFsmStorage,
    SQLiteRepository,
    configure_repository,
)
from services.tg_retry import RetryRequestMiddleware

from menus import service_menu, start, amounts_menu, payment_menu, faqs, referal_menu, confirm_payment_menu, reviews_menu
from services.notification_service import Mailer
from services.scheduler import start_scheduler
from services.maintenance import MaintenanceMiddleware, load_broke
from services.two_pay_api_webhook import start_webhook_server
from commands import announce, allusers, code_inventory, menulink, maintenance

def _make_session() -> AiohttpSession:
    """
    Сессия Telegram под нестабильный канал.

    force_close=True — каждый запрос (включая long-poll getUpdates) идёт на СВЕЖЕМ
    соединении. Это критично для приёма апдейтов: при keep-alive протухшее
    переиспользуемое соединение могло подвесить getUpdates без таймаута — приём
    вставал (кнопки переставали работать), хотя отправка жила. Надёжность приёма
    важнее лишнего TLS-handshake; основную задержку всё равно сняла file_id-кэш
    (фото шлются строкой, а не файлом).
    """
    session = AiohttpSession()
    session._connector_init["force_close"] = True
    return session


bot = Bot(token=BOT_TOKEN, session=_make_session())
# повтор запросов к Telegram при сетевых обрывах канала
bot.session.middleware(RetryRequestMiddleware())


async def _watchdog():
    """
    Раз в минуту логирует состояние ресурсов — чтобы поймать медленную утечку,
    из-за которой бот «залипает» через 7-8 часов. По логам перед заморозкой будет
    видно, что упёрлось в потолок:
      • tasks безудержно растёт → хендлеры копятся (висят на await, не завершаются);
      • fds растёт → утечка сокетов/файловых дескрипторов;
      • watchdog ВООБЩЕ перестал писать → event loop заблокирован синхронным вызовом.
    """
    pid = os.getpid()
    stuck = 0
    while True:
        try:
            tasks = len(asyncio.all_tasks())
            try:
                fds = len(os.listdir(f"/proc/{pid}/fd"))
            except Exception:
                fds = -1
            msg = f"[watchdog] tasks={tasks} | fds={fds}"

            # «застряли»: хендлеры копятся (висят на await, не завершаются).
            bad = tasks > 80
            stuck = stuck + 1 if bad else 0

            if bad or (fds != -1 and fds > 800):
                logger.warning(msg + f"  <-- ЗАЛИПАНИЕ? (stuck={stuck}мин)")
                # дамп: на каком await копятся задачи (видно виновника)
                if tasks > 80:
                    shown = 0
                    for t in asyncio.all_tasks():
                        if t is asyncio.current_task():
                            continue
                        st = t.get_stack(limit=4)
                        if st:
                            f = st[-1]
                            logger.warning(f"[watchdog] зависшая задача @ "
                                           f"{f.f_code.co_filename}:{f.f_lineno} ({f.f_code.co_name})")
                            shown += 1
                            if shown >= 6:
                                break
            else:
                logger.info(msg)

            # самолечение: «плохо» 5 минут подряд = бот завис и сам не выйдет.
            # Жёстко выходим → systemd перезапустит (Restart=always). Не ждём часами.
            if stuck >= 5:
                logger.critical(f"[watchdog] ЗАЛИПАНИЕ 5 мин подряд — перезапуск. {msg}")
                os._exit(1)
        except Exception:
            logger.exception("[watchdog] error")
        await asyncio.sleep(60)


async def main():
    repository = SQLiteRepository(SQLITE_PATH)
    await repository.open()
    configure_repository(repository)
    logger.info("Локальная SQLite открыта: %s", repository.path)
    await load_broke()   # восстановить состояние режима поломки после рестарта
    api_webhook_runner = await start_webhook_server(bot, repository)

    watchdog_task = asyncio.create_task(_watchdog())

    dp = Dispatcher(
        storage=SQLiteFsmStorage(repository),
        events_isolation=SimpleEventIsolation(),
    )

    # режим поломки: перехватывает все нажатия кнопок раньше остальных хендлеров
    dp.callback_query.outer_middleware(MaintenanceMiddleware())

    dp.include_router(start.rt)
    dp.include_router(service_menu.rt)
    dp.include_router(amounts_menu.rt)
    dp.include_router(payment_menu.rt)
    dp.include_router(confirm_payment_menu.rt)
    dp.include_router(reviews_menu.rt)
    dp.include_router(faqs.rt)
    dp.include_router(announce.router)
    dp.include_router(referal_menu.rt)
    dp.include_router(allusers.rt)
    dp.include_router(code_inventory.router)
    dp.include_router(menulink.router)
    dp.include_router(maintenance.router)
    mailer = Mailer(bot, logger)
    await mailer.start()

    dp["mailer"] = mailer
    scheduler = await start_scheduler(mailer)
    dp["scheduler"] = scheduler

    logger.info("SQLite, API-клиент и webhook запущены, запускаем бота...")

    # 3. запуск

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

        # 1. вотчдог
        watchdog_task.cancel()
        with suppress(asyncio.CancelledError):
            await watchdog_task

        # 2. сначала останавливаем источник фоновых рассылок, затем их воркеры
        with suppress(Exception):
            scheduler.shutdown(wait=False)

        # 3. воркеры рассылки
        with suppress(Exception):
            await mailer.stop()

        # 4. HTTP-сервер событий API
        with suppress(Exception):
            await api_webhook_runner.cleanup()

        # 5. локальное состояние закрываем после HTTP-сервера событий
        with suppress(Exception):
            await repository.close()

        # 6. сессия бота — в самом конце
        with suppress(Exception):
            await bot.session.close()

        logger.info("Завершились чисто.")


if __name__ == "__main__":
    asyncio.run(main())
