from datetime import datetime, timedelta

import gspread

from config.utils import logger
from repository.database.database import get_daily_transactions_stats


class MarketingReportService:

    def __init__(self):
        self.gc = gspread.service_account(
            filename="repository/sheets/creds.json"
        )

        self.spreadsheet = self.gc.open("Отчет маркетинг 2change")
        self.sheet = self.spreadsheet.worksheet("app store бот")

    async def write_daily_report(self):

        # 1. берём статистику за вчера
        stats = await get_daily_transactions_stats()

        transactions = stats["transactions"]
        total_sum = stats["amount"]

        # 2. дата (вчера)
        date_str = (datetime.now() - timedelta(days=1)).strftime("%d.%m")

        # 3. формат суммы: 10 000,00
        formatted_sum = f"{total_sum:,.2f}".replace(",", " ").replace(".", ",")

        # 4. строка для записи
        row = [
            date_str,        # A
            "",              # B (пусто)
            transactions,    # C
            formatted_sum    # D
        ]

        # 5. append в таблицу
        self.sheet.append_row(
            row,
            value_input_option="USER_ENTERED"
        )

        logger.info(
            f"[MarketingReport] Добавили строку: "
            f"{date_str} | {transactions} | {formatted_sum}"
        )