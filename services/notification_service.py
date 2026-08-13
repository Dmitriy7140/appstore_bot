from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
import asyncio
import time
from asyncio import Queue
from contextlib import suppress
from aiogram import Bot
from dataclasses import dataclass, field


@dataclass
class _MailingBatch:
    remaining: int
    success: int = 0
    failed: int = 0
    done: asyncio.Event = field(default_factory=asyncio.Event)



class Mailer:
    def __init__(self, bot: Bot, logger, workers: int = 3, rate: float = 20.0):
        self.bot = bot
        self.logger = logger
        self.workers = workers
        self.queue: Queue = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

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
            telegram_id, source_chat_id, source_message_id, batch = await self.queue.get()
            try:
                while True:
                    try:
                        await self._throttle()
                        await self.bot.copy_message(
                            chat_id=telegram_id,
                            from_chat_id=source_chat_id,
                            message_id=source_message_id,
                        )
                        batch.success += 1
                        break
                    except TelegramRetryAfter as e:
                        await asyncio.sleep(e.retry_after + 0.5)

            except TelegramForbiddenError:
                batch.failed += 1

            except Exception as e:
                batch.failed += 1
                self.logger.exception(f"Ошибка {telegram_id}: {e}")

            finally:
                batch.remaining -= 1
                if batch.remaining == 0:
                    batch.done.set()
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
        return await self.send_copy_to_many(users, msg.chat.id, msg.message_id)

    async def send_copy_to_many(
        self,
        users,
        source_chat_id: int,
        source_message_id: int,
    ):
        users = list(users)
        if not users:
            return 0, 0

        batch = _MailingBatch(remaining=len(users))
        for user_id in users:
            await self.queue.put(
                (user_id, source_chat_id, source_message_id, batch)
            )

        await batch.done.wait()

        return batch.success, batch.failed
