from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
import asyncio
import time
from asyncio import Queue
from contextlib import suppress
from aiogram import Bot



class Mailer:
    def __init__(self, bot: Bot, logger, workers: int = 3, rate: float = 20.0):
        self.bot = bot
        self.logger = logger
        self.workers = workers
        self.queue: Queue = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

        self.success = 0
        self.failed = 0

        # Глобальный троттл на ВСЕ воркеры: не больше `rate` сообщений/с суммарно.
        # У Telegram лимит ~30/с на бота; держим рассылку ниже (20/с), чтобы всегда
        # оставался запас для транзакционных сообщений (выдача кода) — иначе массовая
        # рассылка выедала весь бюджет и продажи падали с 429.
        self._min_interval = 1.0 / rate
        self._rate_lock = asyncio.Lock()
        self._next_slot = 0.0

    async def _throttle(self):
        """Разносит отправки во времени так, чтобы суммарный темп не превышал rate."""
        async with self._rate_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_slot = max(now, self._next_slot) + self._min_interval

    async def worker(self):
        while True:
            telegram_id, msg = await self.queue.get()
            try:
                await self._throttle()
                await self.bot.copy_message(
                    chat_id=telegram_id,
                    from_chat_id=msg.chat.id,
                    message_id=msg.message_id
                )
                self.success += 1

            except TelegramRetryAfter as e:
                # даже с троттлом прилетел флуд-контроль — ждём и возвращаем в очередь
                await asyncio.sleep(e.retry_after + 0.5)
                await self.queue.put((telegram_id, msg))

            except TelegramForbiddenError:
                self.failed += 1

            except Exception as e:
                self.failed += 1
                self.logger.exception(f"Ошибка {telegram_id}: {e}")

            finally:
                self.queue.task_done()

    async def start(self):
        self._tasks = [asyncio.create_task(self.worker()) for _ in range(self.workers)]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with suppress(asyncio.CancelledError):
                await t
        self._tasks.clear()

    async def send_to_many(self, users, msg: Message):
        self.success = 0
        self.failed = 0

        for user_id in users:
            await self.queue.put((user_id, msg))


        await self.queue.join()

        return self.success, self.failed