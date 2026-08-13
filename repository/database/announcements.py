from datetime import time

from repository.database.database import get_pool


async def list_scheduled_announcements() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT weekday, send_time, audience, source_chat_id,
                   source_message_id, created_by, enabled, last_sent_at,
                   last_success, last_failed
            FROM scheduled_announcements
            WHERE enabled = TRUE
            ORDER BY weekday
        """)
    return [dict(row) for row in rows]


async def get_scheduled_announcement(weekday: int) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT weekday, send_time, audience, source_chat_id,
                   source_message_id, created_by, enabled, last_sent_at,
                   last_success, last_failed
            FROM scheduled_announcements
            WHERE weekday = $1 AND enabled = TRUE
        """, weekday)
    return dict(row) if row else None


async def upsert_scheduled_announcement(
    *,
    weekday: int,
    send_time: time,
    audience: str,
    source_chat_id: int,
    source_message_id: int,
    created_by: int,
) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO scheduled_announcements (
                weekday, send_time, audience, source_chat_id,
                source_message_id, created_by
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (weekday) DO UPDATE SET
                send_time = EXCLUDED.send_time,
                audience = EXCLUDED.audience,
                source_chat_id = EXCLUDED.source_chat_id,
                source_message_id = EXCLUDED.source_message_id,
                created_by = EXCLUDED.created_by,
                enabled = TRUE,
                updated_at = now()
            RETURNING weekday, send_time, audience, source_chat_id,
                      source_message_id, created_by, enabled, last_sent_at,
                      last_success, last_failed
        """, weekday, send_time, audience, source_chat_id, source_message_id, created_by)
    return dict(row)


async def delete_scheduled_announcement(weekday: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM scheduled_announcements WHERE weekday = $1",
            weekday,
        )
    return result == "DELETE 1"


async def mark_scheduled_announcement_sent(
    weekday: int,
    success: int,
    failed: int,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE scheduled_announcements
            SET last_sent_at = now(), last_success = $2, last_failed = $3
            WHERE weekday = $1
        """, weekday, success, failed)
