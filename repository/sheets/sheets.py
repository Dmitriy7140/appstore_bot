import gspread


class Sheets:
    AMOUNT_SHEETS = {
        1:"500",
        1000: "500",
        2000: "1000",
        2500: "1250",
        3000: "1500",
        3500: "1750",
        4000: "2000",
    }

    def __init__(self):
        self.gc = gspread.service_account(filename="repository/sheets/creds.json")
        self.spreadsheet = self.gc.open("appstore_topups")

    def _get_sheet(self, amount: int):
        """
        Возвращает нужный worksheet по сумме
        """
        sheet_name = self.AMOUNT_SHEETS.get(amount)

        if not sheet_name:
            return None

        return self.spreadsheet.worksheet(sheet_name)

    def _is_valid_key(self, value: str) -> bool:
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
                return key

        return None

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
                return True

        return False