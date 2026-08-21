"""
Режим «поломка» (broke).

Когда включён, ЛЮБОЕ нажатие инлайн-кнопки (callback_query) перехватывается
middleware и вместо обычной логики юзеру отдаётся сообщение про менеджера.
Команды (в т.ч. сам тумблер /broke) — это message-события, их middleware не трогает.

Состояние хранится в локальной SQLite (`service_flags`), чтобы режим
переживал перезапуск бота (watchdog/systemd могут его рестартить), и кэшируется
в памяти для горячего пути — middleware дёргается на каждый клик, читать SQLite
каждый раз не нужно.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

from config.utils import logger
from repository.sqlite_storage import get_repository

BROKE_FLAG = "broke"

BROKE_TEXT = (
    "По техническим причинам, оплаты временно производятся через менеджера, "
    "напишите ваш вопрос @MANAGER_2PAY"
)

# Кэш в памяти; источник истины — локальная SQLite.
_broke = False


def is_broke() -> bool:
    return _broke


async def load_broke() -> None:
    """Восстановить состояние из SQLite при старте бота."""
    global _broke
    try:
        _broke = await get_repository().get_flag(BROKE_FLAG)
        logger.info(f"Режим поломки из SQLite: {'ВКЛ' if _broke else 'выкл'}")
    except Exception:
        logger.exception("Не смог загрузить флаг broke из SQLite — считаем выключенным")
        _broke = False


async def set_broke(value: bool) -> None:
    """Переключить режим: обновить SQLite и кэш в памяти."""
    global _broke
    await get_repository().set_flag(BROKE_FLAG, value)
    _broke = value


class MaintenanceMiddleware(BaseMiddleware):
    """Гасит все нажатия кнопок, пока включён режим поломки."""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if _broke:
            # снимаем «часики» на кнопке и шлём сообщение про менеджера
            try:
                await event.answer()
            except Exception:
                pass
            try:
                if event.message:
                    await event.message.answer(BROKE_TEXT)
            except Exception:
                logger.exception("broke: не смог отправить сообщение про менеджера")
            return  # обычный хендлер не вызываем
        return await handler(event, data)
