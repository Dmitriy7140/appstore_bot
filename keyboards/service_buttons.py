
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def service_keyboard(service):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰Пополнить",
                                  callback_data=f"{service}:topup")
             ],
            [InlineKeyboardButton(text="📚Как сменить регион",
                                  url="https://t.me/pay_2change/361")],
            [InlineKeyboardButton(text="🙍‍♂️Отзывы", url="https://t.me/review_2pay")]
           # [InlineKeyboardButton(text="📋Меню",
               #                   callback_data=f"main_menu")],
        ]
    )
