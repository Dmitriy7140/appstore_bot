from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def reviews_keyboard() -> InlineKeyboardMarkup:
    """Кнопки с отзывами о 2pay и переходом к информации о компании."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📣 Отзывы в канале",
                    url="https://t.me/review_2pay",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Отзовик",
                    url="https://otzovik.com/reviews/2pay-servis_dlya_popolneniya_appstore/",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📰 Блог VC.RU",
                    url="https://vc.ru/services/2922986",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏢 О компании",
                    callback_data="company_info",
                )
            ],
        ]
    )
