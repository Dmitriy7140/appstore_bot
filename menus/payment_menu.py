
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router
from services.payments import  RATES
from repository.sheets.sheets import sheets, run_sheet

rt = Router()


@rt.callback_query(lambda c: "/" in c.data and not c.data.startswith("pay/"))
async def handle_amount(callback: CallbackQuery):
    service, amount = callback.data.split("/")

    if amount == "any":
        await callback.message.answer(
            "💰Для указания своей суммы свяжитесь, пожалуйста, с менеджером @MANAGER_2PAY"
        )
        await callback.answer()
        return

    amount = int(amount)

    if await run_sheet(sheets.has_available_keys, RATES[amount]):

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 Перейти к оплате",
                        callback_data=f"pay/{service}/{amount}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📋 Меню",
                        callback_data="main_menu"
                    )
                ]
            ]
        )

        await callback.message.answer(
            text=(
                f"💰 К оплате: {RATES[amount]} рублей\n\n"
                f"Нажмите кнопку ниже для перехода к оплате."
            ),
            reply_markup=keyboard
        )

    else:
        await callback.message.answer(
            "Все ключи раскупили! Для уточнения свяжитесь с менеджером @MANAGER_2PAY"
        )

    await callback.answer()