import asyncio
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router
from services.payments import create_payment, wait_payment, RATES
from repository.sheets.sheets import sheets


rt = Router()


@rt.callback_query(lambda c: "/" in c.data)
async def handle_amount(callback: CallbackQuery):
    service: str
    service, amount = callback.data.split("/")

    if amount == "any":
        await callback.message.answer("💰Для указания своей суммы свяжитесь, пожалуйста, с менеджером @MANAGER_2PAY")
        await callback.answer()
        return

    payment_url, payment_id = await create_payment( int(amount), chat_id= callback.message.chat.id, user_id=callback.message.from_user.id)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=f"{payment_url}")],
            [InlineKeyboardButton(text="📋 Меню", callback_data="main_menu")]
        ]
    )

    if sheets.has_available_keys(RATES[int(amount)]):
        await callback.message.answer(
            text=(
                f"К оплате {RATES[int(amount)]} рублей\n\n"
                f"Ссылка для оплаты 👇\n\n"
                f"После оплаты дождитесь подтверждения ✅"
            ),
            reply_markup=keyboard
        )


        asyncio.create_task(
            wait_payment(
                callback,
                sheets.get_key,
                payment_id
            )
        )
    else:
        await callback.message.answer("Все ключи раскупили! Для уточнения свяжитесь с менеджером @MANAGER_2PAY")


    await callback.answer()