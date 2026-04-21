import asyncpg

from config.utils import logger
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from config.config_env import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST

pool: asyncpg.Pool | None = None



class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ):
        user_id = event.from_user.id
        p = get_pool()

        async with p.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (telegram_id)
                VALUES ($1)
                ON CONFLICT (telegram_id) DO NOTHING
            """, user_id)
        logger.info(f"Удостоверились, что {user_id} есть в базе.")
        return await handler(event, data)


# -------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ
# -------------------------
async def init_db():
    global pool
    pool = await asyncpg.create_pool(
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        host=DB_HOST
    )
    logger.info("Подключились к бд!")

def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("DB is not initialized")
    return pool


# -------------------------
# ТРАНЗАКЦИИ / БИЗНЕС-ЛОГИКА
# -------------------------
async def add_transaction(telegram_id: int, tx_id: str, amount: int):
    p = get_pool()

    async with p.acquire() as conn:
        async with conn.transaction():

            # запись транзакции
            await conn.execute("""
                INSERT INTO appstore_transactions (telegram_id, transaction_id, amount)
                VALUES ($1, $2, $3)
            """, telegram_id, tx_id, amount)

            # обновление суммы пользователя
            await conn.execute("""
                UPDATE users
                SET total_spent = total_spent + $1
                WHERE telegram_id = $2
            """, amount, telegram_id)
            logger.info("Обновили транзакции в базе!")