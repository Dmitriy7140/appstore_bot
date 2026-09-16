from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config.utils import IsAdmin, logger
from services.two_pay_api_client import (
    CodeInventoryStock,
    TwoPayApiError,
    get_code_inventory,
)


router = Router()


@router.message(Command("codes"), IsAdmin())
async def show_code_inventory(message: Message) -> None:
    try:
        inventory = await get_code_inventory()
    except TwoPayApiError:
        logger.exception("Could not read 2PAY code inventory")
        await message.answer(
            "❌ Не удалось получить остатки со склада. Проверьте журнал бота."
        )
        return
    await message.answer(_inventory_message(inventory), parse_mode="HTML")


def _inventory_message(inventory: CodeInventoryStock, *, heading: bool = True) -> str:
    lines: list[str] = []
    if heading:
        lines.extend(
            [
                "🔑 <b>Остатки App Store на складе</b>",
                "",
            ]
        )
    lines.append(f"Всего доступно: <b>{inventory.total_available}</b>")
    for region in inventory.regions:
        title, currency = {
            "tr": ("🇹🇷 Турция", "₺"),
            "us": ("🇺🇸 США", "$"),
        }.get(region.region.lower(), (html.escape(region.region.upper()), ""))
        lines.extend(["", f"{title}: <b>{region.available}</b>"])
        for item in region.nominals:
            nominal = f"{item.nominal}{currency}" if currency else str(item.nominal)
            lines.append(
                f"• {nominal}: <b>{item.available}</b>"
            )
    lines.extend(["", "Пополнение кодов — через складскую админку."])
    return "\n".join(lines)
