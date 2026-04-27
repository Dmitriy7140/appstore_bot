from os import getenv
from dotenv import load_dotenv
TEST_MODE=False
load_dotenv()
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
else:
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