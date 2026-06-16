import asyncio
import os
import socket
import requests.sessions

# gspread и yookassa SDK ходят по сети через requests, по умолчанию БЕЗ таймаута → при
# сбое/недоступности Google Sheets запрос виснет НАВСЕГДА: поток пула run_sheet застревает,
# а все хендлеры, ждущие его, копятся (tasks растут до сотен) — это и есть «залип через 7-8ч».
# socket.setdefaulttimeout закрывает только connect-фазу и не всегда бьёт по read у requests,
# поэтому вешаем ЯВНЫЙ таймаут на КАЖДЫЙ requests-вызов — теперь он физически не зависнет.
socket.setdefaulttimeout(20)

_orig_requests_request = requests.sessions.Session.request
def _requests_request_with_timeout(self, *args, **kwargs):
    kwargs.setdefault("timeout", 20)
    return _orig_requests_request(self, *args, **kwargs)
requests.sessions.Session.request = _requests_request_with_timeout

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
    Раз в минуту логирует состояние ресурсов — чтобы ПОЙМАТЬ медленную утечку,
    из-за которой бот «залипает» через 7-8 часов. По логам перед заморозкой будет
    видно, что упёрлось в потолок:
      • db_pool idle падает до 0 и держится → исчерпан пул соединений БД (где-то держат коннект);
      • tasks безудержно растёт → хендлеры копятся (висят на await, не завершаются);
      • fds растёт → утечка сокетов/файловых дескрипторов;
      • watchdog ВООБЩЕ перестал писать → event loop заблокирован синхронным вызовом.
    """
    pid = os.getpid()
    stuck = 0
    while True:
        try:
            pool = database.pool
            size = pool.get_size() if pool is not None else -1
            idle = pool.get_idle_size() if pool is not None else -1
            tasks = len(asyncio.all_tasks())
            try:
                fds = len(os.listdir(f"/proc/{pid}/fd"))
            except Exception:
                fds = -1
            msg = f"[watchdog] db_pool size={size} idle={idle} | tasks={tasks} | fds={fds}"

            # «застряли»: хендлеры копятся (висят на await, не завершаются). Норма tasks ~ 8-20.
            # Доп.признак — пул создан, но все коннекты заняты.
            bad = tasks > 80 or (size > 0 and idle == 0)
            stuck = stuck + 1 if bad else 0

            if bad or (fds != -1 and fds > 800):
                logger.warning(msg + f"  <-- ЗАЛИПАНИЕ? (stuck={stuck}мин)")
                # дамп: на каком await копятся задачи (видно виновника — run_sheet/send_message/acquire)
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

    await database.init_db()

    anal_sheets = AnalSheets()
    anal_task = asyncio.create_task(anal_loop(anal_sheets))
    watchdog_task = asyncio.create_task(_watchdog())

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

        # 2. фоновая аналитика + вотчдог
        anal_task.cancel()
        with suppress(asyncio.CancelledError):
            await anal_task

        watchdog_task.cancel()
        with suppress(asyncio.CancelledError):
            await watchdog_task

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