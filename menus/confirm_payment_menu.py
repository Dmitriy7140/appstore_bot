from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

from services.payment_provider import create_payment
from services.rates import RATES
from config.utils import IsAdmin

rt = Router()


# -------------------------
# ВРЕМЕННО: тестовая покупка кода на 10₺ за 16₽ (лист "10").
# Только для админа, чтобы обычные юзеры не увидели дешёвый номинал.
# Удалить после теста вместе с записями 10/16 в RATES/REV_RATES/ALL_SHEETS.
# -------------------------
@rt.message(Command("test10"), IsAdmin())
async def test_buy_10(message: Message):
    payment_url, _payment_id = await create_payment(
        10,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await message.answer(
        "🧪 Тест: код на 10₺ за 16₽\n\nСсылка для оплаты 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 16₽", url=payment_url)],
        ]),
    )


# -------------------------
# CALLBACK
# -------------------------
# Создаём платёж и отдаём ссылку. Подтверждение оплаты и выдача ключа
# происходят асинхронно в callback'е активной кассы (см. services/payment_provider.py;
# по умолчанию Альфа-Банк — services/alfabank_webhook.py).
# Контекст (chat_id/user_id/номинал) сохраняется на стороне бота и поднимается по заказу.
@rt.callback_query(lambda c: c.data.startswith("pay/"))
async def process_payment(callback: CallbackQuery):

    _, service, amount = callback.data.split("/")
    amount = int(amount)

    payment_url, _payment_id = await create_payment(
        amount,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
        [InlineKeyboardButton(text="Прочти перед оплатой", callback_data="asfaq_payment")],
        [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")]
    ])

    await callback.message.answer(
        f"К оплате {RATES[amount]} рублей\n\n"
        f"Ссылка для оплаты 👇\n\n"
        f"После оплаты дождитесь подтверждения ✅",
        reply_markup=keyboard
    )

    await callback.answer()
