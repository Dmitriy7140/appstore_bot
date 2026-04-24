
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def service_keyboard(service):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰Пополнить",
                                  callback_data=f"{service}:topup")
             ],
            [InlineKeyboardButton(text="📚Как сменить регион",
                                  callback_data="asfaq_region")],
            [InlineKeyboardButton(text="🙍‍♂️Отзывы", url="https://t.me/review_2pay")],
           [InlineKeyboardButton(text="📌Часто задаваемые вопросы", url='https://telegra.ph/CHastye-voprosy-po-smene-regiona-i-popolneniyu-App-Store-04-24')]
        ]
    )
