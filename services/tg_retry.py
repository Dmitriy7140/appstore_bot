import asyncio

from aiogram.exceptions import TelegramNetworkError
from aiogram.client.session.middlewares.base import BaseRequestMiddleware

from config.utils import logger


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
