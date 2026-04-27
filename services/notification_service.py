from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
import asyncio
from asyncio import Queue
from aiogram import Bot

from config.config_env import TEST_MODE


class Mailer:
    def __init__(self, bot: Bot, logger, workers: int = 3):
        self.bot = bot
        self.logger = logger
        self.workers = workers
        self.queue: Queue = asyncio.Queue()

        self.success = 0
        self.failed = 0

    async def worker(self):
        while True:
            telegram_id, msg = await self.queue.get()
            try:
                await self.bot.copy_message(
                    chat_id=telegram_id,
                    from_chat_id=msg.chat.id,
                    message_id=msg.message_id
                )
                self.success += 1
                await asyncio.sleep(0.05)

            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                await self.queue.put((telegram_id, msg))

            except TelegramForbiddenError:
                self.failed += 1

            except Exception as e:
                self.failed += 1
                self.logger.exception(f"Ошибка {telegram_id}: {e}")

            finally:
                self.queue.task_done()

    async def start(self):
        for _ in range(self.workers):
            asyncio.create_task(self.worker())

    async def send_to_many(self, users, msg: Message):
        self.success = 0
        self.failed = 0
        if TEST_MODE:
            for user_id in users:
                await self.queue.put((user_id, msg))
        else:
            for (user_id,) in users:
                await self.queue.put((user_id, msg))

        await self.queue.join()

        return self.success, self.failed