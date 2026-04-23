import gspread
import random

from config.utils import logger


class Sheets:
    ALL_SHEETS = {
        1:"100",
        300: "100",
        750: "250",
        1500: "500",
        3000: "1000",
        3750: "1250",
        4500: "1500",
        5250: "1750",
        6000: "2000",
        "adress":"adress"

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

sheets = Sheets()