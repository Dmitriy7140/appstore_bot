"""Runtime configuration for the Telegram-only appstore bot.

The 2PAY API owns customers, payments, transactions, referrals and link
attribution. SQLite contains only Telegram-local and operational bot state.
"""

from os import getenv

from dotenv import load_dotenv


load_dotenv()


TEST_MODE = getenv("TEST_MODE", "False").strip().lower() == "true"
BOT_TOKEN = getenv("TEST_BOT_TOKEN") if TEST_MODE else getenv("BOT_TOKEN")
BOT_URL = getenv("TEST_BOT_URL") if TEST_MODE else getenv("BOT_URL")
ADMIN_CHAT_ID = getenv("ADMIN_CHAT_ID")
ADMIN_IDS = [
    int(value)
    for value in getenv("ADMIN_IDS", "").split(",")
    if value.strip()
]


def _optional_chat_id(name: str, default: str) -> int | None:
    """Read a Telegram chat ID, allowing an empty value to disable a job."""
    value = getenv(name, default).strip()
    if not value:
        return None
    try:
        chat_id = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a Telegram chat ID") from error
    if chat_id == 0:
        raise ValueError(f"{name} must not be zero")
    return chat_id


# Daily website-sales report. Override the ID in .env or leave it empty to
# disable the scheduled post entirely.
DAILY_SALES_REPORT_CHAT_ID = _optional_chat_id(
    "DAILY_SALES_REPORT_CHAT_ID", "-1004486126389"
)
DAILY_SALES_REPORT_HOUR = int(getenv("DAILY_SALES_REPORT_HOUR", "0"))
DAILY_SALES_REPORT_MINUTE = int(getenv("DAILY_SALES_REPORT_MINUTE", "21"))
if not 0 <= DAILY_SALES_REPORT_HOUR <= 23:
    raise ValueError("DAILY_SALES_REPORT_HOUR must be in 0..23")
if not 0 <= DAILY_SALES_REPORT_MINUTE <= 59:
    raise ValueError("DAILY_SALES_REPORT_MINUTE must be in 0..59")

# Local bot state only. Never store API customer/payment/referral data here.
SQLITE_PATH = getenv("SQLITE_PATH", "data/appstore_bot.sqlite3")
API_DELIVERY_LEASE_SECONDS = int(getenv("API_DELIVERY_LEASE_SECONDS", "120"))
if API_DELIVERY_LEASE_SECONDS <= 0:
    raise ValueError("API_DELIVERY_LEASE_SECONDS must be positive")

# API -> bot: signed, public HTTPS callback proxied to this local listener.
TWO_PAY_API_WEBHOOK_HOST = getenv("TWO_PAY_API_WEBHOOK_HOST", "127.0.0.1")
TWO_PAY_API_WEBHOOK_PORT = int(getenv("TWO_PAY_API_WEBHOOK_PORT", "8081"))
TWO_PAY_API_WEBHOOK_PATH = getenv("TWO_PAY_API_WEBHOOK_PATH", "/internal/2pay/events")
TWO_PAY_API_WEBHOOK_TOKEN = getenv("TWO_PAY_API_WEBHOOK_TOKEN", "")
TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS = int(
    getenv("TWO_PAY_API_WEBHOOK_MAX_AGE_SECONDS", "300")
)

# Bot -> API: private, TLS-protected calls. The API checks these tokens
# separately, so an audience leak cannot be used to modify bot state.
TWO_PAY_API_BASE_URL = getenv("TWO_PAY_API_BASE_URL", "https://api.2pay.money").rstrip("/")
TWO_PAY_API_INGEST_TOKEN = getenv("TWO_PAY_API_INGEST_TOKEN", "")
TWO_PAY_API_AUDIENCE_TOKEN = getenv("TWO_PAY_API_AUDIENCE_TOKEN", "")
TWO_PAY_API_TIMEOUT_SECONDS = float(getenv("TWO_PAY_API_TIMEOUT_SECONDS", "10"))
TWO_PAY_API_START_TIMEOUT_SECONDS = float(
    getenv("TWO_PAY_API_START_TIMEOUT_SECONDS", "3")
)
if TWO_PAY_API_START_TIMEOUT_SECONDS <= 0:
    raise ValueError("TWO_PAY_API_START_TIMEOUT_SECONDS must be positive")
TWO_PAY_API_INVENTORY_REFRESH_TIMEOUT_SECONDS = float(
    getenv("TWO_PAY_API_INVENTORY_REFRESH_TIMEOUT_SECONDS", "120")
)
if TWO_PAY_API_INVENTORY_REFRESH_TIMEOUT_SECONDS <= 0:
    raise ValueError("TWO_PAY_API_INVENTORY_REFRESH_TIMEOUT_SECONDS must be positive")
TWO_PAY_API_DEEP_LINK_URL = getenv(
    "TWO_PAY_API_DEEP_LINK_URL", f"{TWO_PAY_API_BASE_URL}/v1/bot/deep-links"
)
TWO_PAY_API_DEEP_LINK_TIMEOUT_SECONDS = float(
    getenv("TWO_PAY_API_DEEP_LINK_TIMEOUT_SECONDS", "5")
)
