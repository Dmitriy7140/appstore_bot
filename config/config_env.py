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


# Прямые платежи в боте отключены без возможности включить их через .env.
# Покупка проходит в TMA; бот лишь открывает Mini App и обслуживает выдачу
# кодов/реферальных наград после подтверждённой покупки.
PAYMENT_PROVIDER = "disabled"

# =========================================================================
# ROBOKASSA (агрегатор — активная касса)
# =========================================================================
ROBOKASSA_MERCHANT_LOGIN = getenv("ROBOKASSA_MERCHANT_LOGIN", "")
ROBOKASSA_PASSWORD1 = getenv("ROBOKASSA_PASSWORD1", "")   # подпись создания платежа
ROBOKASSA_PASSWORD2 = getenv("ROBOKASSA_PASSWORD2", "")   # проверка подписи ResultURL
# Алгоритм хеша подписи — ДОЛЖЕН совпадать с настройкой в ЛК Робокассы.
ROBOKASSA_HASH_ALGO = getenv("ROBOKASSA_HASH_ALGO", "md5").strip().lower()
# Тестовый режим: IsTest=1 (и пароли берём ТЕСТОВЫЕ из ЛК).
ROBOKASSA_IS_TEST = getenv("ROBOKASSA_IS_TEST", "False") == "True"
ROBOKASSA_PAYMENT_URL = getenv(
    "ROBOKASSA_PAYMENT_URL", "https://auth.robokassa.ru/Merchant/Index.aspx"
)
# Путь ResultURL (этот URL прописывается в ЛК Робокассы; за nginx+HTTPS).
ROBOKASSA_RESULT_PATH = getenv("ROBOKASSA_RESULT_PATH", "/robokassa/result")
ROBOKASSA_CULTURE = getenv("ROBOKASSA_CULTURE", "ru")

# --- Фискализация (54-ФЗ) через Робокассу. Если в ЛК включена фискализация,
# Receipt ОБЯЗАТЕЛЕН, иначе оплата отклоняется. Схему/ставку сверьте с ЛК. ---
ROBOKASSA_FISCAL = getenv("ROBOKASSA_FISCAL", "False") == "True"
ROBOKASSA_TAX = getenv("ROBOKASSA_TAX", "none")                # none/vat0/vat10/vat20/…
ROBOKASSA_PAYMENT_METHOD = getenv("ROBOKASSA_PAYMENT_METHOD", "full_payment")
ROBOKASSA_PAYMENT_OBJECT = getenv("ROBOKASSA_PAYMENT_OBJECT", "service")
# Система налогообложения для чека: osn / usn_income / usn_income_outcome / envd /
# esn / patent. Пусто — берётся значение по умолчанию из ЛК Robokassa.
ROBOKASSA_SNO = getenv("ROBOKASSA_SNO", "")
# Email получателя чека (в подпись не входит). Пусто — Robokassa спросит на форме.
ROBOKASSA_EMAIL = getenv("ROBOKASSA_EMAIL", "")

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
