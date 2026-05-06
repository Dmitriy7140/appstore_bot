from aiogram import Router
from aiogram.types import CallbackQuery, CopyTextButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.config_env import TEST_MODE

rt = Router()

@rt.callback_query(lambda c: c.data == "asref")
async def as_ref_menu(callback: CallbackQuery):
    text = ("<b>Получите 100 лир на оплату подписок за каждого друга 🔥</b>\n\n"
            "Пригласите друга в бот — и после его первого пополнения мы отправим вам Apple Gift Card на 100 лир.\n"
            "Карту можно использовать для оплаты App Store, iCloud, Apple Music, Telegram Premium и других сервисов.\n\n"
            "<b>Как получить бонус:</b>\n"
            " 1. Скопируйте свою реферальную ссылку\n"
            " 2. Отправьте её другу\n"
            " 3. После первого пополнения друга вы получите Apple Gift Card на 100 лир\n\n"
            "Приглашайте друзей и оплачивайте подписки выгоднее.")
    await callback.message.answer(text, reply_markup=ref_keyboard(callback.from_user.id), parse_mode="HTML")
    await callback.answer()
def ref_keyboard(user_id):
    url = f"https://t.me/Official_2paybot?start=ref_{user_id}_as"
    if TEST_MODE:
        url = f"https://t.me/appstore_cash_bot?start=ref_{user_id}_as"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Скопировать ссылку", copy_text=CopyTextButton(text=url))
    return builder.as_markup()

