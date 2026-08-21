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
    refresh_code_inventory,
)


router = Router()


@router.message(Command("codes"), IsAdmin())
async def show_code_inventory(message: Message) -> None:
    try:
        inventory = await get_code_inventory()
    except TwoPayApiError:
        logger.exception("Could not read 2PAY code inventory")
        await message.answer(
            "❌ Не удалось получить остатки кодов из API. Проверьте журнал бота."
        )
        return
    await message.answer(_inventory_message(inventory), parse_mode="HTML")


@router.message(Command("refreshcodes"), IsAdmin())
async def refresh_codes(message: Message) -> None:
    progress = await message.answer(
        "⏳ Обновляю кэш кодов из Google Sheets. Это может занять до двух минут…"
    )
    try:
        inventory = await refresh_code_inventory()
    except TwoPayApiError:
        logger.exception("Could not refresh 2PAY code inventory")
        await progress.edit_text(
            "❌ Не удалось полностью обновить кэш кодов. "
            "Часть номиналов могла обновиться; подробности находятся в журнале API."
        )
        return
    await progress.edit_text(
        "✅ <b>Кэш кодов обновлён</b>\n\n" + _inventory_message(inventory, heading=False),
        parse_mode="HTML",
    )


def _inventory_message(inventory: CodeInventoryStock, *, heading: bool = True) -> str:
    lines: list[str] = []
    if heading:
        lines.extend(
            [
                "🔑 <b>Остатки кодов в API</b>",
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
                f"• {nominal}: <b>{item.available}</b>/{item.cache_limit}"
            )
    return "\n".join(lines)
