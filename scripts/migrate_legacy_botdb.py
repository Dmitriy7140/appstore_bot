#!/usr/bin/env python3
"""Import the compatible bot data from a legacy PostgreSQL plain-text dump.

The script is deliberately conservative:
* it only reads COPY blocks for users, appstore_transactions, invite_links and
  referrals;
* it validates the legacy relations before connecting to PostgreSQL;
* it always performs a transactional dry run first; and
* it refuses to write if a transaction or referral would disagree with an
  already-imported record.

Usage (from the bot directory):
    .venv/Scripts/python scripts/migrate_legacy_botdb.py \
        C:/Users/<user>/Downloads/iich/botdb.sql --env-file .env

Add --apply only after reviewing the dry-run report.  DATABASE_URL has
precedence over DB_HOST/DB_NAME/DB_USER/DB_PASSWORD and may be supplied either
by the environment or the env file.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import asyncpg


SOURCE_TABLES = {
    "users": ("telegram_id", "joined_at", "total_spent", "is_banned", "link", "state"),
    "appstore_transactions": ("id", "telegram_id", "transaction_id", "amount", "created_at"),
    "invite_links": ("link", "followed"),
    "referrals": ("user_id", "service", "invited_by", "activated", "reward_given", "created_at"),
}
COPY_START = re.compile(r"^COPY public\.([a-z_]+) \(([^)]+)\) FROM stdin;$")
ESCAPED_COPY_TEXT = re.compile(r"\\([0-7]{1,3}|[bfnrtv\\])")


@dataclass(frozen=True)
class LegacyUser:
    telegram_id: int
    joined_at: datetime
    total_spent: int
    link: str | None
    state: str | None


@dataclass(frozen=True)
class LegacyTransaction:
    telegram_id: int
    transaction_id: str
    amount: int
    created_at: datetime


@dataclass(frozen=True)
class LegacyInviteLink:
    link: str
    followed: int


@dataclass(frozen=True)
class LegacyReferral:
    telegram_id: int
    invited_by_telegram_id: int
    activated: bool
    reward_given: bool
    created_at: datetime


@dataclass(frozen=True)
class LegacyData:
    users: list[LegacyUser]
    transactions: list[LegacyTransaction]
    invite_links: list[LegacyInviteLink]
    referrals: list[LegacyReferral]
    digest: str


def decode_copy_value(value: str) -> str | None:
    """Decode PostgreSQL COPY text format, preserving a real SQL NULL."""
    if value == r"\N":
        return None

    def replace(match: re.Match[str]) -> str:
        escaped = match.group(1)
        simple = {
            "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
            "v": "\v", "\\": "\\",
        }
        if escaped in simple:
            return simple[escaped]
        return chr(int(escaped, 8))

    return ESCAPED_COPY_TEXT.sub(replace, value)


def parse_copy_blocks(dump_path: Path) -> dict[str, list[dict[str, str | None]]]:
    sections: dict[str, list[dict[str, str | None]]] = {name: [] for name in SOURCE_TABLES}
    active_name: str | None = None
    active_columns: tuple[str, ...] = ()

    with dump_path.open("r", encoding="utf-8") as dump_file:
        for line_number, raw_line in enumerate(dump_file, start=1):
            line = raw_line.rstrip("\n\r")
            if active_name is None:
                start = COPY_START.match(line)
                if start and start.group(1) in SOURCE_TABLES:
                    active_name = start.group(1)
                    active_columns = tuple(column.strip() for column in start.group(2).split(","))
                    expected_columns = SOURCE_TABLES[active_name]
                    if active_columns != expected_columns:
                        raise ValueError(
                            f"{active_name}: unexpected COPY columns {active_columns}; "
                            f"expected {expected_columns}"
                        )
                continue

            if line == r"\.":
                active_name = None
                active_columns = ()
                continue

            fields = line.split("\t")
            if len(fields) != len(active_columns):
                raise ValueError(
                    f"{active_name}: malformed COPY row at line {line_number}; "
                    f"expected {len(active_columns)} fields, got {len(fields)}"
                )
            sections[active_name].append(
                dict(zip(active_columns, (decode_copy_value(value) for value in fields), strict=True))
            )

    if active_name is not None:
        raise ValueError(f"{active_name}: COPY block is not terminated by \\.")
    missing = [name for name, rows in sections.items() if not rows]
    if missing:
        raise ValueError(f"Dump contains no data for: {', '.join(missing)}")
    return sections


def required(row: dict[str, str | None], field: str, table: str) -> str:
    value = row[field]
    if value is None or not value:
        raise ValueError(f"{table}.{field} must not be NULL or empty")
    return value


def parse_timestamp(value: str, source_timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed
    return parsed.replace(tzinfo=source_timezone)


def parse_bool(value: str, field: str) -> bool:
    if value == "t":
        return True
    if value == "f":
        return False
    raise ValueError(f"{field} must be t or f, got {value!r}")


def load_legacy_data(dump_path: Path, source_timezone: ZoneInfo) -> LegacyData:
    sections = parse_copy_blocks(dump_path)
    users = [
        LegacyUser(
            telegram_id=int(required(row, "telegram_id", "users")),
            joined_at=parse_timestamp(required(row, "joined_at", "users"), source_timezone),
            total_spent=int(required(row, "total_spent", "users")),
            link=row["link"],
            state=row["state"],
        )
        for row in sections["users"]
    ]
    transactions = [
        LegacyTransaction(
            telegram_id=int(required(row, "telegram_id", "appstore_transactions")),
            transaction_id=required(row, "transaction_id", "appstore_transactions"),
            amount=int(required(row, "amount", "appstore_transactions")),
            created_at=parse_timestamp(required(row, "created_at", "appstore_transactions"), source_timezone),
        )
        for row in sections["appstore_transactions"]
    ]
    invite_links = [
        LegacyInviteLink(
            link=required(row, "link", "invite_links"),
            followed=int(required(row, "followed", "invite_links")),
        )
        for row in sections["invite_links"]
    ]
    referrals = [
        LegacyReferral(
            telegram_id=int(required(row, "user_id", "referrals")),
            invited_by_telegram_id=int(required(row, "invited_by", "referrals")),
            activated=parse_bool(required(row, "activated", "referrals"), "referrals.activated"),
            reward_given=parse_bool(required(row, "reward_given", "referrals"), "referrals.reward_given"),
            created_at=parse_timestamp(required(row, "created_at", "referrals"), source_timezone),
        )
        for row in sections["referrals"]
    ]
    validate_legacy_data(users, transactions, invite_links, referrals)
    return LegacyData(
        users=users,
        transactions=transactions,
        invite_links=invite_links,
        referrals=referrals,
        digest=hashlib.sha256(dump_path.read_bytes()).hexdigest(),
    )


def duplicates(values: Iterable[object]) -> list[object]:
    counts = Counter(values)
    return [value for value, count in counts.items() if count > 1]


def validate_legacy_data(
    users: list[LegacyUser],
    transactions: list[LegacyTransaction],
    invite_links: list[LegacyInviteLink],
    referrals: list[LegacyReferral],
) -> None:
    user_ids = {user.telegram_id for user in users}
    if len(user_ids) != len(users):
        raise ValueError("users contains duplicate telegram_id values")
    if any(user.telegram_id <= 0 or user.total_spent < 0 for user in users):
        raise ValueError("users contains an invalid telegram_id or negative total_spent")
    if duplicates(transaction.transaction_id for transaction in transactions):
        raise ValueError("appstore_transactions contains duplicate transaction_id values")
    if any(transaction.telegram_id not in user_ids or transaction.amount <= 0 for transaction in transactions):
        raise ValueError("transactions contain an unknown user or a non-positive amount")
    if duplicates(link.link for link in invite_links):
        raise ValueError("invite_links contains duplicate links")
    if any(link.followed < 0 for link in invite_links):
        raise ValueError("invite_links contains a negative followed count")
    if duplicates(referral.telegram_id for referral in referrals):
        raise ValueError("referrals contains more than one referral for a user")
    for referral in referrals:
        if referral.telegram_id not in user_ids or referral.invited_by_telegram_id not in user_ids:
            raise ValueError("referrals contains a user absent from users")
        if referral.telegram_id == referral.invited_by_telegram_id:
            raise ValueError("referrals contains a self-referral")
        if referral.reward_given and not referral.activated:
            raise ValueError("referrals has reward_given=true while activated=false")
    totals = Counter()
    for transaction in transactions:
        totals[transaction.telegram_id] += transaction.amount
    mismatch = [user.telegram_id for user in users if totals[user.telegram_id] != user.total_spent]
    if mismatch:
        raise ValueError(f"total_spent does not match transactions for {len(mismatch)} users")


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Environment file is not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def database_url() -> str:
    if value := os.getenv("DATABASE_URL"):
        return value
    required_names = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required_names if not os.getenv(name)]
    if missing:
        raise RuntimeError("Set DATABASE_URL or: " + ", ".join(missing))
    host = os.environ["DB_HOST"]
    database = quote(os.environ["DB_NAME"], safe="")
    username = quote(os.environ["DB_USER"], safe="")
    password = quote(os.environ["DB_PASSWORD"], safe="")
    return f"postgresql://{username}:{password}@{host}/{database}"


async def require_target_schema(connection: asyncpg.Connection) -> None:
    required_tables = ("users", "appstore_transactions", "invite_links", "referrals")
    missing = [
        table for table in required_tables
        if await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is None
    ]
    if missing:
        raise RuntimeError("Target does not have the shared bot schema: " + ", ".join(missing))


async def stage_data(connection: asyncpg.Connection, data: LegacyData) -> None:
    await connection.execute("""
        CREATE TEMP TABLE legacy_users (
            telegram_id BIGINT PRIMARY KEY,
            joined_at TIMESTAMPTZ NOT NULL,
            total_spent INTEGER NOT NULL,
            link TEXT,
            state TEXT
        ) ON COMMIT DROP;
        CREATE TEMP TABLE legacy_transactions (
            telegram_id BIGINT NOT NULL,
            transaction_id TEXT PRIMARY KEY,
            amount INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        ) ON COMMIT DROP;
        CREATE TEMP TABLE legacy_invite_links (
            link TEXT PRIMARY KEY,
            followed INTEGER NOT NULL
        ) ON COMMIT DROP;
        CREATE TEMP TABLE legacy_referrals (
            telegram_id BIGINT PRIMARY KEY,
            invited_by_telegram_id BIGINT NOT NULL,
            activated BOOLEAN NOT NULL,
            reward_given BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        ) ON COMMIT DROP;
    """)
    await connection.copy_records_to_table(
        "legacy_users",
        records=[(u.telegram_id, u.joined_at, u.total_spent, u.link, u.state) for u in data.users],
        columns=("telegram_id", "joined_at", "total_spent", "link", "state"),
    )
    await connection.copy_records_to_table(
        "legacy_transactions",
        records=[(t.telegram_id, t.transaction_id, t.amount, t.created_at) for t in data.transactions],
        columns=("telegram_id", "transaction_id", "amount", "created_at"),
    )
    await connection.copy_records_to_table(
        "legacy_invite_links",
        records=[(link.link, link.followed) for link in data.invite_links],
        columns=("link", "followed"),
    )
    await connection.copy_records_to_table(
        "legacy_referrals",
        records=[(
            referral.telegram_id,
            referral.invited_by_telegram_id,
            referral.activated,
            referral.reward_given,
            referral.created_at,
        ) for referral in data.referrals],
        columns=("telegram_id", "invited_by_telegram_id", "activated", "reward_given", "created_at"),
    )


async def target_conflicts(connection: asyncpg.Connection) -> dict[str, int]:
    return {
        "transactions": int(await connection.fetchval("""
            SELECT count(*)
            FROM legacy_transactions AS legacy
            JOIN appstore_transactions AS current ON current.transaction_id = legacy.transaction_id
            JOIN users AS existing_user ON existing_user.id = current.user_id
            WHERE existing_user.telegram_id IS DISTINCT FROM legacy.telegram_id
               OR current.amount IS DISTINCT FROM legacy.amount
        """)),
        "referrals": int(await connection.fetchval("""
            SELECT count(*)
            FROM legacy_referrals AS legacy
            JOIN users AS referred ON referred.telegram_id = legacy.telegram_id
            JOIN users AS inviter ON inviter.telegram_id = legacy.invited_by_telegram_id
            JOIN referrals AS current ON current.user_id = referred.id
            WHERE current.invited_by IS DISTINCT FROM inviter.id
        """)),
    }


async def migration_plan(connection: asyncpg.Connection) -> dict[str, int]:
    row = await connection.fetchrow("""
        SELECT
            (SELECT count(*) FROM legacy_users AS legacy
             LEFT JOIN users AS current USING (telegram_id)
             WHERE current.id IS NULL) AS users_to_insert,
            (SELECT count(*) FROM legacy_transactions AS legacy
             LEFT JOIN appstore_transactions AS current USING (transaction_id)
             WHERE current.transaction_id IS NULL) AS transactions_to_insert,
            (SELECT count(*) FROM legacy_invite_links AS legacy
             LEFT JOIN invite_links AS current USING (link)
             WHERE current.link IS NULL) AS invite_links_to_insert,
            (SELECT count(*) FROM legacy_referrals AS legacy
             LEFT JOIN users AS referred ON referred.telegram_id = legacy.telegram_id
             LEFT JOIN referrals AS current ON current.user_id = referred.id
             WHERE current.user_id IS NULL) AS referrals_to_insert
    """)
    return {name: int(value) for name, value in dict(row).items()}


async def apply_migration(connection: asyncpg.Connection) -> dict[str, int]:
    results: dict[str, int] = {}
    results["users"] = int((await connection.execute("""
        INSERT INTO users (telegram_id, state, total_spent, link, created_at, updated_at)
        SELECT telegram_id, state, total_spent, link, joined_at, joined_at
        FROM legacy_users
        ON CONFLICT (telegram_id) DO UPDATE
        SET state = COALESCE(users.state, EXCLUDED.state),
            total_spent = GREATEST(users.total_spent, EXCLUDED.total_spent),
            link = COALESCE(users.link, EXCLUDED.link),
            created_at = LEAST(users.created_at, EXCLUDED.created_at),
            updated_at = GREATEST(users.updated_at, EXCLUDED.updated_at)
    """)).rsplit(" ", 1)[1])
    results["invite_links"] = int((await connection.execute("""
        INSERT INTO invite_links (link, followed)
        SELECT link, followed FROM legacy_invite_links
        ON CONFLICT (link) DO UPDATE
        SET followed = GREATEST(invite_links.followed, EXCLUDED.followed)
    """)).rsplit(" ", 1)[1])
    results["transactions"] = int((await connection.execute("""
        INSERT INTO appstore_transactions
            (transaction_id, user_id, telegram_id, email, amount, source, created_at)
        SELECT legacy.transaction_id, user_row.id, legacy.telegram_id, NULL,
               legacy.amount, 'bot', legacy.created_at
        FROM legacy_transactions AS legacy
        JOIN users AS user_row ON user_row.telegram_id = legacy.telegram_id
        ON CONFLICT (transaction_id) DO NOTHING
    """)).rsplit(" ", 1)[1])
    results["referrals"] = int((await connection.execute("""
        INSERT INTO referrals (user_id, invited_by, activated, reward_given, created_at)
        SELECT referred.id, inviter.id, legacy.activated, legacy.reward_given, legacy.created_at
        FROM legacy_referrals AS legacy
        JOIN users AS referred ON referred.telegram_id = legacy.telegram_id
        JOIN users AS inviter ON inviter.telegram_id = legacy.invited_by_telegram_id
        ON CONFLICT (user_id) DO NOTHING
    """)).rsplit(" ", 1)[1])
    await connection.execute("""
        WITH imported_totals AS (
            SELECT tx.user_id, sum(tx.amount)::INTEGER AS total_spent
            FROM appstore_transactions AS tx
            JOIN users AS user_row ON user_row.id = tx.user_id
            JOIN legacy_users AS legacy ON legacy.telegram_id = user_row.telegram_id
            GROUP BY tx.user_id
        )
        UPDATE users AS user_row
        SET total_spent = GREATEST(user_row.total_spent, imported_totals.total_spent),
            updated_at = GREATEST(user_row.updated_at, now())
        FROM imported_totals
        WHERE user_row.id = imported_totals.user_id
    """)
    return results


async def run(data: LegacyData, apply: bool) -> tuple[dict[str, int], dict[str, int] | None]:
    connection = await asyncpg.connect(database_url())
    try:
        async with connection.transaction():
            await require_target_schema(connection)
            await stage_data(connection, data)
            conflicts = await target_conflicts(connection)
            if any(conflicts.values()):
                raise RuntimeError(
                    "Target conflicts detected: "
                    + ", ".join(f"{kind}={count}" for kind, count in conflicts.items() if count)
                )
            plan = await migration_plan(connection)
            if not apply:
                return plan, None
            result = await apply_migration(connection)
            return plan, result
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="Path to botdb.sql")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--source-timezone",
        default="UTC",
        help="Timezone that was used by timestamp-without-time-zone fields in the old DB (default: UTC)",
    )
    parser.add_argument("--apply", action="store_true", help="Commit the migration; omit for a transactional dry run")
    args = parser.parse_args()

    if not args.dump.is_file():
        parser.error(f"Dump is not a readable file: {args.dump}")
    try:
        timezone = ZoneInfo(args.source_timezone)
        data = load_legacy_data(args.dump, timezone)
        load_env_file(args.env_file)
        plan, result = asyncio.run(run(data, args.apply))
    except Exception as error:  # Keep secrets out of the normal output.
        print(f"Migration aborted: {error}", file=sys.stderr)
        return 1

    print(f"Dump SHA-256: {data.digest}")
    print(
        "Source validated: "
        f"users={len(data.users)}, transactions={len(data.transactions)}, "
        f"invite_links={len(data.invite_links)}, referrals={len(data.referrals)}"
    )
    print("Target plan: " + ", ".join(f"{name}={count}" for name, count in plan.items()))
    if result is None:
        print("Dry run successful. Re-run the same command with --apply to commit it.")
    else:
        print("Committed: " + ", ".join(f"{name}={count}" for name, count in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
