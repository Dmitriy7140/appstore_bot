import logging

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from config.config_env import ADMIN_IDS
logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s %(funcName)s %(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs.log', mode="w", encoding='utf-8'),
        logging.StreamHandler()
    ]

)

logger = logging.getLogger(__name__)





class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        return user_id in ADMIN_IDS