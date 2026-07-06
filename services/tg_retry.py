import asyncio

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.client.session.middlewares.base import BaseRequestMiddleware

from config.utils import logger


async def send_flood_safe(factory, *, attempts: int = 5, cap: float = 30.0):
    """
    Выполнить вызов к Telegram, переживая флуд-контроль (429 TelegramRetryAfter).

    Нужно для ТРАНЗАКЦИОННЫХ сообщений (выдача кода, уведомление о транзакции):
    во время массовой рассылки лимит бота (~30/с) исчерпан, и обычный send_message
    падает с 429 → код не доходит до покупателя. Здесь мы ждём указанный Telegram
    интервал и повторяем, чтобы продажа всё равно закрылась.

    factory() должна создавать СВЕЖУЮ корутину на каждую попытку
    (например: lambda: bot.send_message(...)).
    """
    for attempt in range(attempts):
        try:
            return await factory()
        except TelegramRetryAfter as e:
            if attempt == attempts - 1:
                raise
            delay = min(e.retry_after, cap) + 0.5
            logger.warning(
                f"429 flood control: ждём {delay:.1f}s и повторяем "
                f"(попытка {attempt + 1}/{attempts})"
            )
            await asyncio.sleep(delay)


class RetryRequestMiddleware(BaseRequestMiddleware):
    """
    Повторяет запросы к Telegram при СЕТЕВЫХ сбоях
    (ServerDisconnectedError / Request timeout).

    Зачем: канал до api.telegram.org нестабилен — соединение иногда рвётся
    на полпути. Сбои спорадические, поэтому повтор почти всегда проходит.
    Каждая попытка уходит на свежем соединении (Bot создан с force_close=True),
    так что повтор не натыкается на то же протухшее соединение.

    Повторяем ТОЛЬКО TelegramNetworkError — логические ошибки Telegram
    (TelegramBadRequest, Forbidden и т.п.) пробрасываем сразу, их повтор не имеет смысла.
    """

    def __init__(self, retries: int = 3, base_delay: float = 0.5):
        self.retries = retries
        self.base_delay = base_delay

    async def __call__(self, make_request, bot, method):
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                return await make_request(bot, method)
            except TelegramNetworkError as e:
                last_exc = e
                if attempt < self.retries:
                    delay = self.base_delay * attempt
                    logger.warning(
                        f"TG network error ({type(e).__name__}) on "
                        f"{type(method).__name__}: попытка {attempt}/{self.retries}, "
                        f"повтор через {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
        # все попытки исчерпаны — пробрасываем последнюю ошибку
        raise last_exc
