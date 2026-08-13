import asyncpg

from config.utils import logger
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from config.config_env import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, ADMIN_CHAT_ID

from repository.sheets.sheets import sheets, run_sheet

from asyncio import Queue


pool: asyncpg.Pool | None = None

REQUIRED_TABLES = (
    "users",
    "invite_links",
    "referrals",
    "appstore_transactions",
    "processed_payments",
    "used_codes",
    "media_cache",
    "survey_bonus",
    "bot_flags",
    "scheduled_announcements",
)


SCHEDULED_ANNOUNCEMENTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS scheduled_announcements (
        weekday SMALLINT PRIMARY KEY,
        send_time TIME NOT NULL,
        audience TEXT NOT NULL CHECK (audience IN ('all', 'paid', 'rfool', 'others')),
        source_chat_id BIGINT NOT NULL,
        source_message_id BIGINT NOT NULL,
        created_by BIGINT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_sent_at TIMESTAMPTZ,
        last_success INTEGER,
        last_failed INTEGER,
        CONSTRAINT scheduled_announcements_weekday_check
            CHECK (weekday BETWEEN 0 AND 6)
    )
"""

SCHEDULED_ANNOUNCEMENTS_WEEKDAY_MIGRATION = """
    ALTER TABLE scheduled_announcements
        DROP CONSTRAINT IF EXISTS scheduled_announcements_weekday_check;
    ALTER TABLE scheduled_announcements
        ADD CONSTRAINT scheduled_announcements_weekday_check
        CHECK (weekday BETWEEN 0 AND 6);
"""



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
async def _legacy_init_db():
    global pool
    pool = await asyncpg.create_pool(                   #type:ignore
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        host=DB_HOST
    )
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_payments (
                payment_id TEXT PRIMARY KEY,
                created_at TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS media_cache (
                key TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        # опрос 2PAY: наличие строки = юзер прошёл опрос и получил (или ему причитается)
        # бонус. PRIMARY KEY на user_id даёт защиту «1 бонус на 1 user_id».
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS survey_bonus (
                user_id BIGINT PRIMARY KEY,
                completed_at TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        # флаги-тумблеры бота (например "broke" — режим поломки)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_flags (
                key TEXT PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
        # Заказы Альфа-Банка: callback шлюза приходит GET-запросом и НЕ несёт
        # наши метаданные (кому выдать ключ) — только orderNumber/mdOrder. Поэтому
        # при регистрации платежа складываем сюда контекст, а в вебхуке достаём его
        # по order_number. nominal — номинал в лирах (аргумент create_payment),
        # amount_kopecks — сумма к оплате в копейках (для сверки с ответом шлюза).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alfa_orders (
                order_number TEXT PRIMARY KEY,
                user_id      BIGINT NOT NULL,
                chat_id      BIGINT NOT NULL,
                nominal      INTEGER NOT NULL,
                amount_kopecks INTEGER NOT NULL,
                md_order     TEXT,
                source       TEXT,
                created_at   TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        # Заказы Robokassa: InvId должен быть уникальным целым числом — берём его
        # из SERIAL. При регистрации платежа складываем контекст (кому выдать ключ),
        # в ResultURL достаём по InvId. amount_rub — сумма к оплате в рублях.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS robokassa_orders (
                invoice_id  SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                chat_id     BIGINT NOT NULL,
                nominal     INTEGER NOT NULL,
                amount_rub  INTEGER NOT NULL,
                source      TEXT,
                created_at  TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
    logger.info("Подключились к бд!")


# -------------------------
# ЗАКАЗЫ ROBOKASSA (контекст платежа для ResultURL)
# -------------------------
async def init_db():
    """Connect the bot to the schema owned and migrated by the API project."""
    global pool
    pool = await asyncpg.create_pool(  # type: ignore
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        host=DB_HOST,
    )
    async with pool.acquire() as conn:
        # В отличие от базовой схемы эта таблица добавлена после первого релиза,
        # поэтому создаём её идемпотентно и для уже существующих инсталляций.
        await conn.execute(SCHEDULED_ANNOUNCEMENTS_SCHEMA)
        # Ранние версии разрешали только 0..4 (пн–пт). Обновляем ограничение,
        # чтобы существующая база принимала субботу (5) и воскресенье (6).
        await conn.execute(SCHEDULED_ANNOUNCEMENTS_WEEKDAY_MIGRATION)
        missing = [
            table
            for table in REQUIRED_TABLES
            if await conn.fetchval("SELECT to_regclass($1)", f"public.{table}") is None
        ]
    if missing:
        await close_pool()
        raise RuntimeError(
            "Shared database schema is not installed. "
            "Apply 2pay-api/db/migrations/0001_shared_schema.sql first. "
            f"Missing tables: {', '.join(missing)}"
        )
    logger.info("Shared database schema verified")


async def create_robokassa_order(
    user_id: int,
    chat_id: int,
    nominal: int,
    amount_rub: int,
    source: str | None = None,
) -> int:
    """Создать заказ и вернуть его invoice_id (это и есть InvId для Robokassa)."""
    p = get_pool()
    async with p.acquire() as conn:
        inv_id = await conn.fetchval("""
            INSERT INTO robokassa_orders (user_id, chat_id, nominal, amount_rub, source)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING invoice_id
        """, int(user_id), int(chat_id), nominal, amount_rub, source)
    return int(inv_id)


async def get_robokassa_order(invoice_id: int):
    """Вернуть контекст заказа по InvId (или None)."""
    p = get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT invoice_id, user_id, chat_id, nominal, amount_rub, source
            FROM robokassa_orders
            WHERE invoice_id = $1
        """, invoice_id)
    return dict(row) if row else None


# -------------------------
# ЗАКАЗЫ АЛЬФА-БАНКА (контекст платежа для callback-уведомлений)
# -------------------------
async def create_alfa_order(
    order_number: str,
    user_id: int,
    chat_id: int,
    nominal: int,
    amount_kopecks: int,
    source: str | None = None,
):
    """Сохранить контекст заказа перед редиректом на платёжную форму Альфы."""
    p = get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
            INSERT INTO alfa_orders
                (order_number, user_id, chat_id, nominal, amount_kopecks, source)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (order_number) DO NOTHING
        """, order_number, user_id, chat_id, nominal, amount_kopecks, source)


async def get_alfa_order(order_number: str):
    """Вернуть контекст заказа по order_number (или None, если не наш заказ)."""
    p = get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT order_number, user_id, chat_id, nominal, amount_kopecks,
                   md_order, source
            FROM alfa_orders
            WHERE order_number = $1
        """, order_number)
    return dict(row) if row else None


async def attach_alfa_md_order(order_number: str, md_order: str):
    """Проставить mdOrder (id заказа в шлюзе) — приходит в первом callback."""
    p = get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
            UPDATE alfa_orders SET md_order = $2 WHERE order_number = $1
        """, order_number, md_order)


# -------------------------
# ФЛАГИ-ТУМБЛЕРЫ БОТА
# -------------------------
async def get_flag(key: str) -> bool:
    p = get_pool()
    async with p.acquire() as conn:
        val = await conn.fetchval("SELECT enabled FROM bot_flags WHERE key = $1", key)
    return bool(val)


async def set_flag(key: str, enabled: bool):
    p = get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
            INSERT INTO bot_flags (key, enabled)
            VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET enabled = EXCLUDED.enabled
        """, key, enabled)


# -------------------------
# ОПРОС 2PAY (бонус за прохождение)
# -------------------------
async def has_completed_survey(user_id: int) -> bool:
    """Проходил ли юзер опрос (мягкая проверка для UX перед стартом)."""
    p = get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM survey_bonus WHERE user_id = $1", user_id
        )
    return row is not None


async def claim_survey_bonus(user_id: int) -> bool:
    """
    Атомарно «застолбить» бонус за опрос.
    True  — застолбили первыми, бонус нужно выдать.
    False — юзер уже получал бонус, повторно не выдаём.
    """
    p = get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO survey_bonus (user_id)
            VALUES ($1)
            ON CONFLICT (user_id) DO NOTHING
            RETURNING user_id
        """, user_id)
    return row is not None


# -------------------------
# ИДЕМПОТЕНТНОСТЬ ПЛАТЕЖЕЙ (вебхуки ЮKassa)
# -------------------------
async def claim_payment(payment_id: str) -> bool:
    """
    Атомарно «застолбить» платёж перед выдачей ключа.
    True  — застолбили первыми, нужно обработать.
    False — платёж уже обработан/обрабатывается, выдачу повторять нельзя.
    """
    p = get_pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO processed_payments (payment_id)
            VALUES ($1)
            ON CONFLICT (payment_id) DO NOTHING
            RETURNING payment_id
        """, payment_id)
    return row is not None


async def release_payment(payment_id: str):
    """
    Снять метку, если выдача упала ДО извлечения ключа —
    тогда повторное уведомление ЮKassa сможет обработать платёж заново.
    """
    p = get_pool()
    async with p.acquire() as conn:
        await conn.execute(
            "DELETE FROM processed_payments WHERE payment_id = $1",
            payment_id
        )

def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("DB is not initialized")
    return pool


async def close_pool():
    """Корректно закрыть пул соединений при остановке бота."""
    global pool
    if pool is not None:
        await pool.close()
        pool = None
        logger.info("Пул БД закрыт")


# -------------------------
# КЭШ file_id ТЕЛЕГРАМА (чтобы не перезаливать фото/видео на плохом канале)
# -------------------------
_media_l1: dict[str, str] = {}   # L1-кэш в памяти перед БД (skip round-trip на горячем пути)


async def get_file_id(key: str) -> str | None:
    cached = _media_l1.get(key)
    if cached is not None:
        return cached
    p = get_pool()
    async with p.acquire() as conn:
        file_id = await conn.fetchval(
            "SELECT file_id FROM media_cache WHERE key = $1", key
        )
    if file_id:
        _media_l1[key] = file_id
    return file_id


async def set_file_id(key: str, file_id: str, kind: str):
    _media_l1[key] = file_id
    p = get_pool()
    async with p.acquire() as conn:
        await conn.execute("""
            INSERT INTO media_cache (key, file_id, kind, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (key) DO UPDATE
            SET file_id = EXCLUDED.file_id, kind = EXCLUDED.kind, updated_at = now()
        """, key, file_id, kind)


# -------------------------
# ТРАНЗАКЦИИ / БИЗНЕС-ЛОГИКА
# -------------------------
async def add_transaction(bot, telegram_id: int, tx_id: str, amount: int):
    p = get_pool()

    async with p.acquire() as conn:
        async with conn.transaction():

            # запись транзакции
            transaction_id = await conn.fetchval("""
                INSERT INTO appstore_transactions (
                    transaction_id, user_id, telegram_id, amount, source
                )
                SELECT $2, id, telegram_id, $3, 'bot'
                FROM users
                WHERE telegram_id = $1
                RETURNING transaction_id
            """, telegram_id, tx_id, amount)
            if transaction_id is None:
                raise RuntimeError(
                    f"Cannot write transaction for unknown Telegram user {telegram_id}"
                )

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

async def get_daily_transactions_stats():
    p = get_pool()

    async with p.acquire() as conn:
        row = await conn.fetchrow("""SELECT
    COUNT(*) AS total_transactions,
    COALESCE(SUM(amount), 0) AS total_amount
FROM appstore_transactions
WHERE telegram_id NOT IN (57713855, 5777995768)
  AND created_at >= (CURRENT_DATE - INTERVAL '1 day') - INTERVAL '3 hours'
  AND created_at < CURRENT_DATE - INTERVAL '3 hours'
        """)

        return {
            "transactions": row["total_transactions"],
            "amount": row["total_amount"]
        }



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

async def _legacy_add_referral(telegram_id: int, payload: str):
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
async def _legacy_process_referral_reward(telegram_id: int):
    p = get_pool()

    # 1. атомарно «застолбить» реферал (короткая транзакция, БЕЗ медленных вызовов внутри)
    async with p.acquire() as conn:
        async with conn.transaction():
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

            await conn.execute("""
                UPDATE referrals
                SET activated = TRUE
                WHERE user_id = $1
            """, telegram_id)
    # ← соединение с БД ОСВОБОЖДЕНО здесь

    # 2. ключ берём ВНЕ соединения с БД: gspread не должен держать коннект из пула —
    #    зависший Sheets иначе исчерпает пул asyncpg и подвесит весь бот.
    #    400 → лист "100" (награда «ключ на 100 лир»); номинала 300 в ALL_SHEETS нет.
    key = await run_sheet(sheets.get_key, 400)

    if not key:
        logger.error("Нет ключей для выдачи реф-награды!")
        # ключ не получен — снимаем «застолблённость», чтобы следующая оплата
        # этого же реферала попробовала выдать награду снова (иначе реферал сгорит)
        async with p.acquire() as conn:
            await conn.execute("""
                UPDATE referrals
                SET activated = FALSE
                WHERE user_id = $1
            """, telegram_id)
        return None

    # 3. фиксируем выдачу отдельной короткой транзакцией
    async with p.acquire() as conn:
        await conn.execute("""
            UPDATE referrals
            SET reward_given = TRUE
            WHERE user_id = $1
        """, telegram_id)

    return {
        "inviter_id": inviter_id,
        "key": key
    }
async def add_referral(telegram_id: int, payload: str):
    """Bind a bot user to one inviter, independently of the old service suffix."""
    try:
        prefix, inviter_telegram_id, *_ = payload.split("_")
        if prefix != "ref":
            return
        inviter_telegram_id = int(inviter_telegram_id)
    except (TypeError, ValueError):
        return

    if telegram_id == inviter_telegram_id:
        return

    p = get_pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            referred_user_id = await conn.fetchval(
                "SELECT id FROM users WHERE telegram_id = $1", telegram_id
            )
            inviter_user_id = await conn.fetchval(
                "SELECT id FROM users WHERE telegram_id = $1", inviter_telegram_id
            )
            if referred_user_id is None or inviter_user_id is None:
                return

            await conn.execute("""
                INSERT INTO referrals (user_id, invited_by)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO NOTHING
            """, referred_user_id, inviter_user_id)


async def process_referral_reward(telegram_id: int):
    """Issue the one referral reward after the referred user's first payment."""
    p = get_pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT referrals.user_id,
                       inviter.telegram_id AS inviter_telegram_id
                FROM referrals
                JOIN users AS referred ON referred.id = referrals.user_id
                JOIN users AS inviter ON inviter.id = referrals.invited_by
                WHERE referred.telegram_id = $1
                  AND referrals.activated = FALSE
                FOR UPDATE OF referrals
            """, telegram_id)
            if row is None or row["inviter_telegram_id"] is None:
                return None

            referred_user_id = row["user_id"]
            inviter_telegram_id = row["inviter_telegram_id"]
            await conn.execute("""
                UPDATE referrals
                SET activated = TRUE, activated_at = now()
                WHERE user_id = $1
            """, referred_user_id)

    key = await run_sheet(sheets.get_key, 400)
    if not key:
        logger.error("No referral reward code is available")
        async with p.acquire() as conn:
            await conn.execute("""
                UPDATE referrals
                SET activated = FALSE, activated_at = NULL
                WHERE user_id = $1
            """, referred_user_id)
        return None

    async with p.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO used_codes (
                    code, nominal, user_id, telegram_id, purpose, source
                )
                SELECT $1, 400, id, telegram_id, 'referral_reward', 'bot'
                FROM users
                WHERE id = (
                    SELECT invited_by FROM referrals WHERE user_id = $2
                )
            """, key, referred_user_id)
            await conn.execute("""
                UPDATE referrals
                SET reward_given = TRUE, reward_given_at = now()
                WHERE user_id = $1
            """, referred_user_id)

    return {"inviter_id": inviter_telegram_id, "key": key}


async def send_referral_reward(bot, inviter_id: int, key: str):
    try:
        user_link = f"tg://user?id={inviter_id}"
        await bot.send_message(
            inviter_id,
            f"🎉 Ваш реферал совершил оплату!\n\nВаш ключ на 100 лир: <code>{key}</code>",
            parse_mode="HTML"
        )
        await bot.send_message(
            ADMIN_CHAT_ID,
            text=(
                f"🎁 Бонус за реферала!\n\n"
                f"👤 Получатель: <a href='{user_link}'>{inviter_id}</a>\n\n"
                f"🔑 Код: <tg-spoiler>{key}</tg-spoiler>"
            ),
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

