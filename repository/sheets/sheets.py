import asyncio
import functools
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import gspread
import random

from config.utils import logger


# Единый пул из ОДНОГО потока для ВСЕХ обращений к Google Sheets (gspread).
# gspread синхронный и не потокобезопасный, а его вызовы медленные (HTTP к Google).
# Один выделенный поток даёт сразу три эффекта:
#   1) вызовы не блокируют event loop (всё уходит через run_in_executor);
#   2) они НЕ забивают дефолтный пул asyncio, где живёт DNS-резолв
#      (getaddrinfo для api.telegram.org) — поэтому Telegram больше не голодает;
#   3) сериализация доступа к таблице убирает гонку за один и тот же ключ.
_SHEETS_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sheets")


async def run_sheet(func, *args, **kwargs):
    """Выполнить синхронный вызов к таблице в выделенном потоке, не блокируя loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_SHEETS_POOL, functools.partial(func, *args, **kwargs))


class Sheets:
    ALL_SHEETS = {
        1:"100",
        400: "100",
        950: "250",
        1750: "500",
        3500: "1000",
        4250: "1250",
        5100: "1500",
        5600: "1750",
        6400: "2000",
        "adress":"adress",
        "used":"used"

    }

    def __init__(self):
        self.gc = gspread.service_account(filename="repository/sheets/creds.json")
        self.spreadsheet = self.gc.open("appstore_topups")
        self.addresses = self._load_addresses()

    def _get_sheet(self, key: int|str):
        """
        Возвращает нужный worksheet по ключу
        """
        sheet_name = self.ALL_SHEETS.get(key)

        if not sheet_name:
            logger.info(f"Отсутствует таблица {key}")
            return None

        return self.spreadsheet.worksheet(sheet_name)

    def _is_valid_key(self, value: str) -> bool|None:
        key = value.strip()
        return len(key) == 16 or len(key) == 19

    def get_key(self, amount: int):
        """
        Берет и удаляет ключ из нужной страницы
        """
        sheet = self._get_sheet(amount)

        if not sheet:
            return None

        values = sheet.col_values(1)

        for i in range(len(values) - 1, -1, -1):
            value = values[i]

            if self._is_valid_key(value):
                key = value.strip()
                sheet.delete_rows(i + 1)
                logger.info("Взяли ключ из таблицы.")
                return key

        return None

    def _load_addresses(self) -> list:
        sheet = self._get_sheet("adress")
        values = sheet.get_all_values()
        logger.info("Загрузили адреса...")
        return [
            {
                "street": data[0],
                "postcode": data[1],
                "city": data[2],
                "phone1": data[3],
                "phone2": data[4],
            }
            for data in values[1:]
        ]

    def get_address(self) -> dict:
        return random.choice(self.addresses)


    def has_available_keys(self, amount: int) -> bool:
        """
        Проверяет наличие ключей в конкретной странице
        """

        sheet = self._get_sheet(amount)

        if not sheet:

            return False

        values = sheet.col_values(1)

        for value in reversed(values):
            if self._is_valid_key(value):
                logger.info("Есть подходящий ключ!")
                return True
        logger.error(f"Ключи на странице {sheet} закончились!")
        return False

    def add_used(self, amount: int, telegram_id: int, code: str):
        """
        Добавляет запись в лист 'used':
        [номинал, telegram_id, код, дата]
        """

        sheet = self._get_sheet("used")

        if not sheet:
            logger.error("Лист 'used' не найден")
            return False

        try:
            now = datetime.now().strftime("%d-%m-%Y %H:%M")

            row = [
                amount,
                telegram_id,
                code,
                now
            ]

            sheet.append_row(row, value_input_option="USER_ENTERED")

            logger.info(f"Добавили использованный код {code} для {telegram_id}")
            return True

        except Exception as e:
            logger.exception(f"Ошибка записи в used: {e}")
            return False
sheets = Sheets()