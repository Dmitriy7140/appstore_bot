import gspread
from config.utils import logger
from repository.database.database import get_links_and_followers
import asyncio


class AnalSheets:
    def __init__(self):
        self.gc = gspread.service_account(filename="creds.json")
        self.ws = self.gc.open("2pay_analysis").worksheet("links")

    async def sync_links(self):
        try:
            db_rows = await get_links_and_followers()

            # читаем текущие данные (A = link)
            sheet_data = self.ws.get_all_values()[1:]  # без заголовка

            # link -> row_number
            link_to_row = {}
            for i, row in enumerate(sheet_data, start=2):
                if row and row[0]:
                    link_to_row[row[0]] = i

            for r in db_rows:
                link = r["link"]
                followed = r["followed"]

                # если ссылка уже есть → обновляем только колонку B
                if link in link_to_row:
                    row_num = link_to_row[link]
                    self.ws.update(f"B{row_num}", [[followed]])

                # если нет → добавляем новую строку
                else:
                    self.ws.append_row([link, followed], value_input_option="RAW")

            logger.info(f"Синхронизировали в таблице с ссылками: {len(db_rows)} рядов")

        except Exception as e:
            logger.error(f"Ошибка в синхронизации таблицы: {e}")

async def anal_loop(anal_sheets: AnalSheets):
    while True:
        await anal_sheets.sync_links()
        await asyncio.sleep(1800)