from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config.config_messages import FAQ_TEXTS

from repository.sheets.sheets import sheets, run_sheet
from services.media_cache import send_cached_media_group


rt = Router()

FAQ_CODE = [
    "static/faqs/as6.MOV",
    "static/faqs/as2.png",
    "static/faqs/as3.png",
]
FAQ_REGION = [
    "static/faqs/as4.png",
    "static/faqs/as5.png",
]
FAQ_IMSTUPID = [
    "static/faqs/imstupid1.jpg",
    "static/faqs/imstupid2.jpg",
    "static/faqs/imstupid3.jpg",
    "static/faqs/imstupid4.jpg",
    "static/faqs/imstupid5.jpg",
]


async def send_region_faq(message: Message):
    """Гайд по смене региона + кнопка «Получить адрес».

    Вынесено отдельно, чтобы это меню можно было показать и по колбэку
    (asfaq_region), и первым сообщением по deep-link (см. menus/deeplinks.py).
    Принимает Message, поэтому target — callback.message ИЛИ message из /start.
    """
    await send_cached_media_group(message, [
        {"path": FAQ_REGION[0], "kind": "photo", "caption": FAQ_TEXTS["asfaq"]["region"], "parse_mode": "HTML"},
        {"path": FAQ_REGION[1], "kind": "photo"},
    ])
    await message.answer(
        "<b>Чтобы получить адрес для смены региона, жмите кнопку ниже 👇</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="Получить адрес",
                    callback_data="asfaq_adress",
                    style="success",
                )
            ]]
        ),
        parse_mode="HTML",
    )


async def send_questions_faq(message: Message):
    """«Ответы на вопросы» — серия фото. Принимает Message: зовётся и из колбэка
    (asfaq_questions), и первым сообщением по deep-link (menus/deeplinks.py)."""
    caption = ('Это самое волнительное — менять что-то в своём iPhone. Но бояться нечего: ваш аккаунт остаётся вашим, ничего не потеряется, а мы рядом на каждом шаге ❤️\n\n'

               '👩 Остались вопросы — менеджер Анна → @manager_2pay\n'
               '🤖 Сменить регион и пополнить App Store → @official_2paybot\n')
    items = [{"path": FAQ_IMSTUPID[0], "kind": "photo", "caption": caption, "parse_mode": "HTML"}]
    items += [{"path": p, "kind": "photo"} for p in FAQ_IMSTUPID[1:]]
    await send_cached_media_group(message, items)


@rt.callback_query(F.data.startswith("asfaq"))
async def send_as_faq(callback: CallbackQuery):
    tag, option = callback.data.split("_")
    if option == "code":
        caption = ("После получения кода:\n\n"
                   "1. Зайдите в App Store и нажмите на иконку вашего имени в верхнем правом углу.\n\n"
                   "2. Нажмите на кнопку \"Redeem Gift Card or Code\"\n\n'"
                   "3. Далее нажмите на \"You can also enter your code manually\"\n\n"
                   "4. Введите полученный код. Теперь вы можете оплачивать подписки!)")
        await send_cached_media_group(callback.message, [
            {"path": FAQ_CODE[0], "kind": "video", "caption": caption},
        ])
        await callback.answer()
    elif option == "region":
        await send_region_faq(callback.message)
        await callback.answer()
    elif option == "adress":
        a=await run_sheet(sheets.get_address)
        text=("<b>Отправляем вам данные Турецкого адреса, вводите без ошибок:\n\n"
              "<i>Текст копируется при нажатии</i>\n"
            f"Street:  <code>{a['street']}</code>\n"
              f"City:  <code>{a['city']}</code>\n"
              f"Postcode:  <code>{a['postcode']}</code>\n"
              f"Phone1:  <code>{a['phone1']}</code>\n"
              f"Phone2:  <code>{a['phone2']}</code></b>\n")
        await callback.message.answer(text, parse_mode="html", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💰Пополнить", callback_data="as:topup")],
                             [InlineKeyboardButton(text="📋Меню", callback_data="main_menu")]]
        ))
        await callback.answer()
    elif option == "payment":
        text=('<code>⚠️ Оплата банковской картой временно недоступна по независящим от нас причинам.\n\n'

              '✅ Подключили альтернативу — теперь можно оплатить через СБП с любого банка России за 5 секунд по QR в приложении вашего банка.\n\n'

              'Ваш 2PAY🩶</code>')
        await callback.message.answer(text, parse_mode="html")
        await callback.answer()
    elif option == "questions":
        await send_questions_faq(callback.message)
        await callback.answer()
