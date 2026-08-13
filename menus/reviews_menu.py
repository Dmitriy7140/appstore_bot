from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from keyboards.reviews_buttons import reviews_keyboard


REVIEWS_MENU_TEXT = "Отзывы на 2pay на разных платформах"

COMPANY_INFO_TEXT = (
    "<b>О компании</b>\n\n"
    "1. <a href=\"https://docs.google.com/document/d/1kHSX7rIoskAvN5XS-04hB0VvDberpRQGkCPj-Js4rbQ/edit\">"
    "Реквизиты и информация</a>\n"
    "2. <a href=\"https://docs.google.com/document/d/1chIzpJ044IRltYbQcH7O8ckCPrJn1CI-PnlFygSu8YI/edit\">"
    "Договор-оферта</a>\n"
    "3. <a href=\"https://docs.google.com/document/d/1Aj3NIl7eQy0ej9qsJeVKFS7p6LWvPj1se0YlYJU0XSE/edit\">"
    "Политика обработки персональных данных</a>\n"
    "4. <a href=\"https://docs.google.com/document/d/1ELXeK_WVoHySEu5o9X090foR6Ixr6G_yb42uqfaI6hU/edit\">"
    "Правила: цены, оплата, доставка и возврат</a>"
)

rt = Router()


async def send_reviews_menu(message: Message):
    """Показывает меню отзывов по сообщению или deep-link."""
    await message.answer(
        REVIEWS_MENU_TEXT,
        reply_markup=reviews_keyboard(),
    )


@rt.callback_query(F.data == "reviews_menu")
async def reviews_menu(callback: CallbackQuery):
    await send_reviews_menu(callback.message)
    await callback.answer()


@rt.callback_query(F.data == "company_info")
async def company_info(callback: CallbackQuery):
    await callback.message.answer(COMPANY_INFO_TEXT, parse_mode="HTML")
    await callback.answer()
