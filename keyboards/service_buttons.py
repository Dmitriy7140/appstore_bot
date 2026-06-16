
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def service_keyboard(service):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆓 Сменить регион БЕСПЛАТНО",
                                  callback_data="asfaq_region")],
            [InlineKeyboardButton(text="💰 Пополнить Apple ID",
                                  callback_data=f"{service}:topup")],
            [InlineKeyboardButton(text="📌 Ответы на ваши вопросы",
                                  callback_data="asfaq_questions")],
            [InlineKeyboardButton(text="🙍‍♂️ Отзывы и гарантии",
                                  url="https://t.me/review_2pay")],
            [InlineKeyboardButton(text="🎁 Бонус 100₺ за друга",
                                  callback_data=f"{service}ref")],
        ]
    )
