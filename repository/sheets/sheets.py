import gspread


class Sheets:
    def __init__(self):
        self.gc = gspread.service_account(filename="repository/sheets/creds.json")
        self.sheet = self.gc.open("appstore_topups").sheet1

    def _is_valid_key(self, value: str) -> bool:
        key = value.strip()
        return len(key) == 16 or len(key) == 19

    def get_key(self):
        """
        Берет и удаляет последний (с конца) валидный ключ
        """
        values = self.sheet.col_values(1)

        for i in range(len(values) - 1, -1, -1):
            value = values[i]

            if self._is_valid_key(value):
                key = value.strip()
                self.sheet.delete_rows(i + 1)
                return key

        return None

    def has_available_keys(self) -> bool:
        """
        Проверяет есть ли валидный ключ (с конца)
        Ничего не удаляет
        """
        values = self.sheet.col_values(1)

        for value in reversed(values):
            if self._is_valid_key(value):
                return True

        return False