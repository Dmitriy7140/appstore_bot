from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

AMOUNTS = [500, 1000, 1250, 1500, 1750, 2000]

def amounts_keyboard(service: str) -> InlineKeyboardMarkup:
    keyboard = []

    service, _ = service.split(":")


    for i in range(0, len(AMOUNTS), 2):
        row = []

        for amount in AMOUNTS[i:i+2]:
            row.append(
                InlineKeyboardButton(
                    text=f"🇹🇷{amount}",
                    callback_data=f"{service}/{amount}"
                )
            )

        keyboard.append(row)


    keyboard.append([
        InlineKeyboardButton(
            text="💰Другая сумма",
            callback_data=f"{service}/any"
        )
    ],

    )
    keyboard.append([InlineKeyboardButton(text="📋Меню", callback_data="main_menu")],)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)