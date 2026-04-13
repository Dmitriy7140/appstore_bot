from aiogram.types import InlineKeyboardMarkup,  InlineKeyboardButton

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
            InlineKeyboardButton(text="🍏AppStore", callback_data="as"),
            #InlineKeyboardButton(text="🤖GooglePlay", callback_data="gp")
             ],
            #[
            #InlineKeyboardButton(text="🎮PlayStation", callback_data="ps"),
            #InlineKeyboardButton(text="🟢Xbox", callback_data="xb"),
            #],
           # [InlineKeyboardButton(text="💻Steam", callback_data="st")],
        ]
    )
