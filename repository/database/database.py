import asyncpg

from config.utils import logger
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from config.config_env import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST

from repository.sheets.sheets import sheets

from asyncio import Queue


pool: asyncpg.Pool | None = None



class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ):
        if not hasattr(event, "from_user") or event.from_user is None:
            return await handler(event, data)

        user_id = event.from_user.id
        p = get_pool()

        async with p.acquire() as conn:
            # создаём пользователя БЕЗ link (null ок)
            await conn.execute("""
                        INSERT INTO users (telegram_id)
                        VALUES ($1)
                        ON CONFLICT DO NOTHING
                    """, user_id)
            user = await conn.fetchrow("""
                        SELECT state, total_spent
                        FROM users
                        WHERE telegram_id = $1
                        """, user_id)
            if user["state"]== "rfool" and user["total_spent"] > 0:
                await conn.execute("""
                        UPDATE users SET state = 'paid'
                        WHERE telegram_id = $1
                        """, user_id)
            if hasattr(event, "data") and event.data == "asfaq_region":
                if user["total_spent"] == 0:
                    await conn.execute("""
                            UPDATE users SET state = 'rfool'
                            WHERE telegram_id = $1
                            """, user_id)
            if user["total_spent"] > 0:
                await conn.execute("""
                UPDATE users SET state = 'paid'
                WHERE telegram_id = $1
                """, user_id)

        return await handler(event, data)

# -------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ
# -------------------------
async def init_db():
    global pool
    pool = await asyncpg.create_pool(                   #type:ignore
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
async def add_transaction(bot, telegram_id: int, tx_id: str, amount: int):
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
    result = await process_referral_reward(telegram_id)

    if result:
        await send_referral_reward(bot,
            result["inviter_id"],
            result["key"]
        )

async def add_client_source(telegram_id: int, payload: str | None):
    p = get_pool()

    async with p.acquire() as conn:

        if payload:
            # 1. сначала гарантируем что ссылка существует
            await conn.execute("""
                INSERT INTO invite_links (link, followed)
                VALUES ($1, 0)
                ON CONFLICT (link) DO NOTHING
            """, payload)

            # 2. увеличиваем счётчик переходов
            await conn.execute("""
                UPDATE invite_links
                SET followed = followed + 1
                WHERE link = $1
            """, payload)

            # 3. привязываем пользователя к ссылке
            await conn.execute("""
                UPDATE users
                SET link = $2
                WHERE telegram_id = $1
            """, telegram_id, payload)

async def add_referral(telegram_id: int, payload: str):
    # payload format: ref_<inviter_id>_<service>
    try:
        _, ref_id_str, service = payload.split("_")
        ref_id = int(ref_id_str)
    except Exception:
        return  # битый payload — игнорируем

    # запрет самореферала
    if telegram_id == ref_id:
        return

    p = get_pool()

    async with p.acquire() as conn:
        async with conn.transaction():

            # проверяем, есть ли уже запись (user_id + service)
            exists = await conn.fetchval("""
                SELECT 1
                FROM referrals
                WHERE user_id = $1 AND service = $2
            """, telegram_id, service)

            if exists:
                return  # уже привязан — ничего не делаем

            # проверяем, существует ли пригласивший
            inviter_exists = await conn.fetchval("""
                SELECT 1 FROM users WHERE telegram_id = $1
            """, ref_id)

            if not inviter_exists:
                return

            # создаём реферал
            await conn.execute("""
                INSERT INTO referrals (user_id, invited_by, service)
                VALUES ($1, $2, $3)
            """, telegram_id, ref_id, service)
async def process_referral_reward(telegram_id: int):
    p = get_pool()

    async with p.acquire() as conn:
        async with conn.transaction():

            # берём НЕобработанный реферал и блокируем строку
            row = await conn.fetchrow("""
                SELECT invited_by, service
                FROM referrals
                WHERE user_id = $1
                  AND activated = FALSE
                FOR UPDATE
            """, telegram_id)

            if not row:
                return None

            inviter_id = row["invited_by"]


            # 1. активируем
            await conn.execute("""
                UPDATE referrals
                SET activated = TRUE
                WHERE user_id = $1
            """, telegram_id)

            # 2. берём ключ
            key = sheets.get_key(300)  # или логика от service/amount

            if not key:
                logger.error("Нет ключей для выдачи!")
                return None

            # 3. фиксируем выдачу (ВАЖНО: до отправки сообщения)
            await conn.execute("""
                UPDATE referrals
                SET reward_given = TRUE
                WHERE user_id = $1
            """, telegram_id)

        key = sheets.get_key(100)
        if not key:
            return None

        return {
            "inviter_id": inviter_id,
            "key": key
            }
async def send_referral_reward(bot, inviter_id: int, key: str):
    try:
        await bot.send_message(
            inviter_id,
            f"🎉 Ваш реферал совершил оплату!\n\nВаш ключ на 100 лир: <code>{key}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception(f"Ошибка отправки реф награды: {e}")


async def get_links_and_followers():
    p = get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("""
                    SELECT link,followed
                    FROM invite_links
                    ORDER BY followed DESC
                """)

        return rows
async def get_user_ids():
    p = get_pool()
    async with p.acquire() as conn:
        rows = await conn.fetch("""
                    SELECT telegram_id
                    FROM users
                    """)
        queue = Queue()
        for (tg_id,) in rows:
            await queue.put(tg_id)

        return queue

async def set_user_state(telegram_id:int, state:str):
    p = get_pool()
    async with p.acquire()as conn:
        await conn.execute("""
        UPDATE users
        SET state = $1
        WHERE telegram_id = $2
        """, state, telegram_id)

async def get_user_ids_by_state(state: str | None):
    p = get_pool()

    async with p.acquire() as conn:

        # 👇 ВСЕ пользователи
        if state == "all" or state is None:
            rows = await conn.fetch("""
                SELECT telegram_id FROM users
            """)

        # 👇 "others" = всё кроме paid и rfool
        elif state == "others":
            rows = await conn.fetch("""
                SELECT telegram_id FROM users
                WHERE state IS NULL
                   OR state NOT IN ('paid', 'rfool')
            """)

        # 👇 конкретные состояния
        else:
            rows = await conn.fetch("""
                SELECT telegram_id FROM users
                WHERE state = $1
            """, state)

    return [row["telegram_id"] for row in rows]

