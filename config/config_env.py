from os import getenv
from dotenv import load_dotenv
load_dotenv()
if getenv("TEST_MODE") == "False":
    TEST_MODE = False
else:
    TEST_MODE = True

if TEST_MODE:
    BOT_TOKEN = getenv("TEST_BOT_TOKEN")
    SHOP_ID=getenv("TEST_SHOP_ID")
    SECRET_KEY=getenv("TEST_SECRET_KEY")
    BOT_URL=getenv("TEST_BOT_URL")
    ADMIN_CHAT_ID=getenv("ADMIN_CHAT_ID")
    DB_USER = getenv("DB_USER")
    DB_PASSWORD = getenv("DB_PASSWORD")
    DB_NAME = getenv("DB_NAME")
    DB_HOST = getenv("DB_HOST")
    ADMIN_IDS = list(map(int, getenv("ADMIN_IDS", "").split(",")))
    WEBHOOK_HOST = getenv("WEBHOOK_HOST", "127.0.0.1")
    WEBHOOK_PORT = int(getenv("WEBHOOK_PORT", "8080"))
    WEBHOOK_PATH = getenv("WEBHOOK_PATH", "/yookassa/webhook")
    YOOKASSA_ALLOWED_IPS = getenv("YOOKASSA_ALLOWED_IPS", "")
    SURVEY_CHAT_ID = int(getenv("SURVEY_CHAT_ID", "-1003922981460"))
    MANAGER_WEBHOOK_URL = getenv("MANAGER_WEBHOOK_URL", "")
else:
    MANAGER_WEBHOOK_URL = getenv("MANAGER_WEBHOOK_URL", "")
    BOT_TOKEN = getenv('BOT_TOKEN')
    SHOP_ID = getenv('SHOP_ID')
    SECRET_KEY = getenv('SECRET_KEY')
    BOT_URL = getenv('BOT_URL')
    ADMIN_CHAT_ID = getenv("ADMIN_CHAT_ID")
    DB_USER = getenv("DB_USER")
    DB_PASSWORD = getenv("DB_PASSWORD")
    DB_NAME = getenv("DB_NAME")
    DB_HOST = getenv("DB_HOST")
    ADMIN_IDS = list(map(int, getenv("ADMIN_IDS", "").split(",")))
    WEBHOOK_HOST = getenv("WEBHOOK_HOST", "127.0.0.1")
    WEBHOOK_PORT = int(getenv("WEBHOOK_PORT", "8080"))
    WEBHOOK_PATH = getenv("WEBHOOK_PATH", "/yookassa/webhook")
    YOOKASSA_ALLOWED_IPS = getenv("YOOKASSA_ALLOWED_IPS", "")
    SURVEY_CHAT_ID = int(getenv("SURVEY_CHAT_ID", "-1003922981460"))


# =========================================================================
# ВЫБОР КАССЫ И НАСТРОЙКИ АЛЬФА-БАНКА (провайдер-независимо от TEST_MODE)
# =========================================================================
# Какая касса активна: "alfa" (по умолчанию) или "yookassa" (спящий режим).
PAYMENT_PROVIDER = getenv("PAYMENT_PROVIDER", "alfa").strip().lower()

# База REST API «Платёжного шлюза» Альфы (оканчивается на /payment/rest/):
#   боевой:   https://pay.alfabank.ru/payment/rest/
#   тестовый: https://alfa.rbsuat.com/payment/rest/
ALFA_API_BASE = getenv("ALFA_API_BASE", "https://pay.alfabank.ru/payment/rest/")

# Аутентификация: либо токен, либо пара логин/пароль (выдаёт Альфа при подключении).
ALFA_TOKEN = getenv("ALFA_TOKEN", "")
ALFA_USERNAME = getenv("ALFA_USERNAME", "")
ALFA_PASSWORD = getenv("ALFA_PASSWORD", "")

# Куда вернуть клиента после оплаты (по умолчанию — в бота).
ALFA_RETURN_URL = getenv("ALFA_RETURN_URL", BOT_URL or "")
ALFA_FAIL_URL = getenv("ALFA_FAIL_URL", "")

# Валюта ISO 4217: 643 — RUB.
ALFA_CURRENCY = getenv("ALFA_CURRENCY", "643")

# Callback-токен для проверки контрольной суммы (симметричная криптография).
# Пусто — уведомления без контрольной суммы (проверяем оплату только через
# getOrderStatusExtended). Задан — дополнительно сверяем HMAC-SHA256.
ALFA_CALLBACK_TOKEN = getenv("ALFA_CALLBACK_TOKEN", "")

# Путь callback-эндпоинта (этот URL прописывается в ЛК Альфы, за nginx c HTTPS).
ALFA_WEBHOOK_PATH = getenv("ALFA_WEBHOOK_PATH", "/alfabank/callback")

# --- Фискализация (54-ФЗ). По умолчанию ВЫКЛ: многие подключения Альфы
# фискализируют на своей стороне (ОФД). Включайте только сверив схему с банком. ---
ALFA_FISCAL = getenv("ALFA_FISCAL", "False") == "True"
ALFA_RECEIPT_EMAIL = getenv("ALFA_RECEIPT_EMAIL", "")
ALFA_TAX_TYPE = int(getenv("ALFA_TAX_TYPE", "0"))     # 0 — без НДС (уточните у Альфы)
ALFA_MEASURE = getenv("ALFA_MEASURE", "шт")