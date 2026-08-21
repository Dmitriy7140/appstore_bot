"""Local SQLite state for the Telegram process.

This database deliberately contains no payments, transactions, customer
profiles, referrals or deep-link attribution. Those remain authoritative in
the 2PAY API PostgreSQL database.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time as unix_time
from collections.abc import Mapping
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Literal

from aiogram.exceptions import DataNotDictLikeError
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey


DeliveryClaim = Literal["claimed", "already_delivered", "in_progress"]


class DeliveryPayloadConflictError(ValueError):
    """The same delivery ID was reused for a different event payload."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS fsm_states (
    bot_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    thread_id INTEGER NOT NULL DEFAULT 0,
    business_connection_id TEXT NOT NULL DEFAULT '',
    destiny TEXT NOT NULL DEFAULT 'default',
    state TEXT,
    data_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
        bot_id, chat_id, user_id, thread_id,
        business_connection_id, destiny
    )
);

CREATE TABLE IF NOT EXISTS scheduled_announcements (
    weekday INTEGER PRIMARY KEY CHECK (weekday BETWEEN 0 AND 6),
    send_time TEXT NOT NULL,
    audience TEXT NOT NULL CHECK (audience IN ('all', 'paid', 'never_paid')),
    source_chat_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL CHECK (source_message_id > 0),
    created_by INTEGER NOT NULL CHECK (created_by > 0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_sent_at TEXT,
    last_success INTEGER,
    last_failed INTEGER
);

CREATE TABLE IF NOT EXISTS telegram_file_cache (
    cache_key TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    media_kind TEXT NOT NULL CHECK (media_kind IN ('photo', 'video')),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_payment_deliveries (
    transaction_id TEXT PRIMARY KEY,
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'delivered')),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until INTEGER,
    telegram_message_id INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS api_referral_reward_deliveries (
    reward_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'delivered')),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until INTEGER,
    telegram_message_id INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS service_flags (
    flag_key TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SQLiteRepository:
    """One-process SQLite repository serialized by an asyncio lock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.executescript(SCHEMA)
        # Cleanup for databases created by the short-lived local_users draft.
        # API PostgreSQL is the only user registry.
        connection.execute("DROP TABLE IF EXISTS local_users")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        self._connection = connection

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLite repository is not open")
        return self._connection

    @staticmethod
    def _fsm_key(key: StorageKey) -> tuple[int, int, int, int, str, str]:
        return (
            key.bot_id,
            key.chat_id,
            key.user_id,
            key.thread_id or 0,
            key.business_connection_id or "",
            key.destiny,
        )

    async def set_fsm_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        async with self._lock:
            self._db().execute(
                """
                INSERT INTO fsm_states (
                    bot_id, chat_id, user_id, thread_id,
                    business_connection_id, destiny, state, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    bot_id, chat_id, user_id, thread_id,
                    business_connection_id, destiny
                ) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at
                """,
                (*self._fsm_key(key), value, _utc_now()),
            )
            self._delete_empty_fsm_record(key)
            self._db().commit()

    async def get_fsm_state(self, key: StorageKey) -> str | None:
        async with self._lock:
            row = self._db().execute(
                """
                SELECT state FROM fsm_states
                WHERE bot_id = ? AND chat_id = ? AND user_id = ? AND thread_id = ?
                  AND business_connection_id = ? AND destiny = ?
                """,
                self._fsm_key(key),
            ).fetchone()
        return None if row is None else row["state"]

    async def set_fsm_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if not isinstance(data, dict):
            raise DataNotDictLikeError(
                f"Data must be a dict or dict-like object, got {type(data).__name__}"
            )
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        async with self._lock:
            self._db().execute(
                """
                INSERT INTO fsm_states (
                    bot_id, chat_id, user_id, thread_id,
                    business_connection_id, destiny, data_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    bot_id, chat_id, user_id, thread_id,
                    business_connection_id, destiny
                ) DO UPDATE SET data_json = excluded.data_json, updated_at = excluded.updated_at
                """,
                (*self._fsm_key(key), encoded, _utc_now()),
            )
            self._delete_empty_fsm_record(key)
            self._db().commit()

    async def get_fsm_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._lock:
            row = self._db().execute(
                """
                SELECT data_json FROM fsm_states
                WHERE bot_id = ? AND chat_id = ? AND user_id = ? AND thread_id = ?
                  AND business_connection_id = ? AND destiny = ?
                """,
                self._fsm_key(key),
            ).fetchone()
        if row is None:
            return {}
        value = json.loads(row["data_json"])
        if not isinstance(value, dict):
            raise RuntimeError("FSM data in SQLite is not an object")
        return value

    def _delete_empty_fsm_record(self, key: StorageKey) -> None:
        self._db().execute(
            """
            DELETE FROM fsm_states
            WHERE bot_id = ? AND chat_id = ? AND user_id = ? AND thread_id = ?
              AND business_connection_id = ? AND destiny = ?
              AND state IS NULL AND data_json = '{}'
            """,
            self._fsm_key(key),
        )

    async def list_schedules(self) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._db().execute(
                "SELECT * FROM scheduled_announcements WHERE enabled = 1 ORDER BY weekday"
            ).fetchall()
        return [self._schedule_row(row) for row in rows]

    async def get_schedule(self, weekday: int) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute(
                "SELECT * FROM scheduled_announcements WHERE weekday = ? AND enabled = 1",
                (weekday,),
            ).fetchone()
        return None if row is None else self._schedule_row(row)

    async def put_schedule(
        self,
        *,
        weekday: int,
        send_time: time,
        audience: str,
        source_chat_id: int,
        source_message_id: int,
        created_by: int,
    ) -> dict[str, Any]:
        if weekday not in range(7) or audience not in {"all", "paid", "never_paid"}:
            raise ValueError("Invalid schedule weekday or audience")
        now = _utc_now()
        async with self._lock:
            self._db().execute(
                """
                INSERT INTO scheduled_announcements (
                    weekday, send_time, audience, source_chat_id,
                    source_message_id, created_by, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(weekday) DO UPDATE SET
                    send_time = excluded.send_time,
                    audience = excluded.audience,
                    source_chat_id = excluded.source_chat_id,
                    source_message_id = excluded.source_message_id,
                    created_by = excluded.created_by,
                    enabled = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    weekday,
                    send_time.strftime("%H:%M:%S"),
                    audience,
                    source_chat_id,
                    source_message_id,
                    created_by,
                    now,
                    now,
                ),
            )
            self._db().commit()
        result = await self.get_schedule(weekday)
        if result is None:  # pragma: no cover - protected by the insert above
            raise RuntimeError("Could not store schedule")
        return result

    async def delete_schedule(self, weekday: int) -> bool:
        async with self._lock:
            cursor = self._db().execute(
                "DELETE FROM scheduled_announcements WHERE weekday = ?", (weekday,)
            )
            self._db().commit()
            return cursor.rowcount > 0

    async def record_schedule_delivery(self, weekday: int, success: int, failed: int) -> None:
        async with self._lock:
            self._db().execute(
                """
                UPDATE scheduled_announcements
                SET last_sent_at = ?, last_success = ?, last_failed = ?, updated_at = ?
                WHERE weekday = ?
                """,
                (_utc_now(), success, failed, _utc_now(), weekday),
            )
            self._db().commit()

    @staticmethod
    def _schedule_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "weekday": row["weekday"],
            "send_time": time.fromisoformat(row["send_time"]),
            "audience": row["audience"],
            "source_chat_id": row["source_chat_id"],
            "source_message_id": row["source_message_id"],
            "created_by": row["created_by"],
            "enabled": bool(row["enabled"]),
            "last_sent_at": row["last_sent_at"],
            "last_success": row["last_success"],
            "last_failed": row["last_failed"],
        }

    async def get_file_id(self, cache_key: str) -> str | None:
        async with self._lock:
            row = self._db().execute(
                "SELECT file_id FROM telegram_file_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return None if row is None else row["file_id"]

    async def put_file_id(self, cache_key: str, file_id: str, media_kind: str) -> None:
        async with self._lock:
            self._db().execute(
                """
                INSERT INTO telegram_file_cache (cache_key, file_id, media_kind, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    file_id = excluded.file_id,
                    media_kind = excluded.media_kind,
                    updated_at = excluded.updated_at
                """,
                (cache_key, file_id, media_kind, _utc_now()),
            )
            self._db().commit()

    async def delete_file_id(self, cache_key: str) -> None:
        async with self._lock:
            self._db().execute(
                "DELETE FROM telegram_file_cache WHERE cache_key = ?", (cache_key,)
            )
            self._db().commit()

    async def get_flag(self, key: str) -> bool:
        async with self._lock:
            row = self._db().execute(
                "SELECT enabled FROM service_flags WHERE flag_key = ?", (key,)
            ).fetchone()
        return False if row is None else bool(row["enabled"])

    async def set_flag(self, key: str, enabled: bool) -> None:
        async with self._lock:
            self._db().execute(
                """
                INSERT INTO service_flags (flag_key, enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(flag_key) DO UPDATE SET
                    enabled = excluded.enabled, updated_at = excluded.updated_at
                """,
                (key, int(enabled), _utc_now()),
            )
            self._db().commit()

    async def claim_payment_delivery(
        self, transaction_id: str, payload_sha256: str, lease_seconds: int
    ) -> DeliveryClaim:
        return await self._claim_delivery(
            table="api_payment_deliveries",
            id_column="transaction_id",
            delivery_id=transaction_id,
            payload_sha256=payload_sha256,
            lease_seconds=lease_seconds,
        )

    async def claim_referral_reward_delivery(
        self,
        reward_id: str,
        transaction_id: str,
        payload_sha256: str,
        lease_seconds: int,
    ) -> DeliveryClaim:
        return await self._claim_delivery(
            table="api_referral_reward_deliveries",
            id_column="reward_id",
            delivery_id=reward_id,
            payload_sha256=payload_sha256,
            lease_seconds=lease_seconds,
            transaction_id=transaction_id,
        )

    async def _claim_delivery(
        self,
        *,
        table: str,
        id_column: str,
        delivery_id: str,
        payload_sha256: str,
        lease_seconds: int,
        transaction_id: str | None = None,
    ) -> DeliveryClaim:
        if table not in {"api_payment_deliveries", "api_referral_reward_deliveries"}:
            raise ValueError("Unsupported delivery table")
        now_epoch = int(unix_time.time())
        now = _utc_now()
        async with self._lock:
            db = self._db()
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    f"SELECT payload_sha256, status, lease_until FROM {table} WHERE {id_column} = ?",
                    (delivery_id,),
                ).fetchone()
                if row is None:
                    if transaction_id is None:
                        db.execute(
                            f"""
                            INSERT INTO {table} (
                                {id_column}, payload_sha256, status, attempts,
                                lease_until, created_at, updated_at
                            ) VALUES (?, ?, 'processing', 1, ?, ?, ?)
                            """,
                            (delivery_id, payload_sha256, now_epoch + lease_seconds, now, now),
                        )
                    else:
                        db.execute(
                            f"""
                            INSERT INTO {table} (
                                {id_column}, transaction_id, payload_sha256, status,
                                attempts, lease_until, created_at, updated_at
                            ) VALUES (?, ?, ?, 'processing', 1, ?, ?, ?)
                            """,
                            (
                                delivery_id,
                                transaction_id,
                                payload_sha256,
                                now_epoch + lease_seconds,
                                now,
                                now,
                            ),
                        )
                    db.commit()
                    return "claimed"
                if row["payload_sha256"] != payload_sha256:
                    db.rollback()
                    raise DeliveryPayloadConflictError(
                        f"Delivery ID {delivery_id!r} has another payload"
                    )
                if row["status"] == "delivered":
                    db.commit()
                    return "already_delivered"
                if row["status"] == "processing" and (row["lease_until"] or 0) > now_epoch:
                    db.commit()
                    return "in_progress"
                db.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'processing', attempts = attempts + 1,
                        lease_until = ?, last_error = NULL, updated_at = ?
                    WHERE {id_column} = ?
                    """,
                    (now_epoch + lease_seconds, now, delivery_id),
                )
                db.commit()
                return "claimed"
            except Exception:
                if db.in_transaction:
                    db.rollback()
                raise

    async def complete_payment_delivery(
        self, transaction_id: str, telegram_message_id: int | None
    ) -> None:
        await self._complete_delivery(
            "api_payment_deliveries", "transaction_id", transaction_id, telegram_message_id
        )

    async def complete_referral_reward_delivery(
        self, reward_id: str, telegram_message_id: int | None
    ) -> None:
        await self._complete_delivery(
            "api_referral_reward_deliveries", "reward_id", reward_id, telegram_message_id
        )

    async def _complete_delivery(
        self, table: str, id_column: str, delivery_id: str, telegram_message_id: int | None
    ) -> None:
        now = _utc_now()
        async with self._lock:
            self._db().execute(
                f"""
                UPDATE {table}
                SET status = 'delivered', lease_until = NULL,
                    telegram_message_id = ?, last_error = NULL,
                    delivered_at = ?, updated_at = ?
                WHERE {id_column} = ?
                """,
                (telegram_message_id, now, now, delivery_id),
            )
            self._db().commit()

    async def fail_payment_delivery(self, transaction_id: str, error: str) -> None:
        await self._fail_delivery(
            "api_payment_deliveries", "transaction_id", transaction_id, error
        )

    async def fail_referral_reward_delivery(self, reward_id: str, error: str) -> None:
        await self._fail_delivery(
            "api_referral_reward_deliveries", "reward_id", reward_id, error
        )

    async def _fail_delivery(
        self, table: str, id_column: str, delivery_id: str, error: str
    ) -> None:
        async with self._lock:
            self._db().execute(
                f"""
                UPDATE {table}
                SET status = 'pending', lease_until = NULL, last_error = ?, updated_at = ?
                WHERE {id_column} = ? AND status != 'delivered'
                """,
                (error[:2000], _utc_now(), delivery_id),
            )
            self._db().commit()


class SQLiteFsmStorage(BaseStorage):
    """Aiogram adapter; the repository lifetime is owned by ``main``."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self.repository = repository

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        await self.repository.set_fsm_state(key, state)

    async def get_state(self, key: StorageKey) -> str | None:
        return await self.repository.get_fsm_state(key)

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self.repository.set_fsm_data(key, data)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return await self.repository.get_fsm_data(key)

    async def close(self) -> None:
        # Dispatcher stops FSM before the API webhook. The shared repository is
        # closed explicitly after the HTTP listener has stopped.
        return None


_repository: SQLiteRepository | None = None


def configure_repository(repository: SQLiteRepository) -> None:
    global _repository
    _repository = repository


def get_repository() -> SQLiteRepository:
    if _repository is None:
        raise RuntimeError("SQLite repository has not been configured")
    return _repository
