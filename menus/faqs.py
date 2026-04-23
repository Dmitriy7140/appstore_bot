from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from config.config_messages import FAQ_TEXTS

from repository.sheets.sheets import sheets


rt = Router()

FAQ_CODE = [
    "static/faqs/as1.png",
    "static/faqs/as2.png",
    "static/faqs/as3.png",
]
FAQ_REGION = [
    "static/faqs/as4.png",
    "static/faqs/as5.png",
]


@rt.callback_query(F.data.startswith("asfaq"))
async def send_as_faq(callback: CallbackQuery):
    tag, option = callback.data.split("_")
    if option == "code":
        media = [
            InputMediaPhoto(
                media=FSInputFile(FAQ_CODE[0]),
                caption=(
                    "Куда вводить код? ⬇️\n\n"
                    "Войдите в App Store → аватарка → "
                    "погасить подарочную карту или код → "
                    "вставьте код и ваш аккаунт будет пополнен! 🙌🏻"
                )
            ),
            InputMediaPhoto(media=FSInputFile(FAQ_CODE[1])),
            InputMediaPhoto(media=FSInputFile(FAQ_CODE[2])),
        ]

        await callback.message.answer_media_group(media)
        await callback.answer()
    elif option == "region":
        media = [
            InputMediaPhoto(
                media=FSInputFile(FAQ_REGION[0]),
                caption = FAQ_TEXTS[tag][option],
                parse_mode="HTML",


            ),
            InputMediaPhoto(media=FSInputFile(FAQ_REGION[1])),


        ]
        await callback.message.answer_media_group(media)
        await callback.message.answer(
            "<b>Чтобы получить адрес для смены региона, жмите кнопку ниже 👇</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="Получить адрес",
                        callback_data="asfaq_adress",
                        style="success",

                    )
                   ]
                ]
            ),
            parse_mode="HTML",
        )
        await callback.answer()
    elif option == "adress":
        a=sheets.get_address()
        text=("<b>Отправляем вам данные Турецкого адреса, вводите без ошибок:\n\n"
              "<i>Текст копируется при нажатии</i>\n"
            f"Street:  <code>{a["street"]}</code>\n"
              f"City:  <code>{a["city"]}</code>\n"
              f"Postcode:  <code>{a["postcode"]}</code>\n"
              f"Phone1:  <code>{a["phone1"]}</code>\n"
              f"Phone2:  <code>{a["phone2"]}</code></b>\n")
        await callback.message.answer(text, parse_mode="html", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💰Пополнить", callback_data="as:topup")],
                             [InlineKeyboardButton(text="📋Меню", callback_data="main_menu")]]
        ))
        await callback.answer()