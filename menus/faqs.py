from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto, FSInputFile

rt = Router()

FAQ_PHOTOS = [
    "static/faqs/as1.png",
    "static/faqs/as2.png",
    "static/faqs/as3.png",
]


@rt.callback_query(F.data == "as_faq")
async def send_as_faq(callback: CallbackQuery):

    media = [
        InputMediaPhoto(
            media=FSInputFile(FAQ_PHOTOS[0]),
            caption=(
                "Куда вводить код? ⬇️\n\n"
                "Войдите в App Store → аватарка → "
                "погасить подарочную карту или код → "
                "вставьте код и ваш аккаунт будет пополнен! 🙌🏻"
            )
        ),
        InputMediaPhoto(media=FSInputFile(FAQ_PHOTOS[1])),
        InputMediaPhoto(media=FSInputFile(FAQ_PHOTOS[2])),
    ]

    await callback.message.answer_media_group(media)
    await callback.answer()