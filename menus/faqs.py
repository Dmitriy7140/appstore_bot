from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config.config_messages import FAQ_TEXTS

from keyboards.webapp_buttons import payment_moved_keyboard
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
    """Гайд по смене региона.

    Вынесено отдельно, чтобы это меню можно было показать и по колбэку
    (asfaq_region), и первым сообщением по deep-link (см. menus/deeplinks.py).
    Принимает Message, поэтому target — callback.message ИЛИ message из /start.
    """
    await send_cached_media_group(message, [
        {"path": FAQ_REGION[0], "kind": "photo", "caption": FAQ_TEXTS["asfaq"]["region"], "parse_mode": "HTML"},
        {"path": FAQ_REGION[1], "kind": "photo"},
    ])


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
        await callback.message.answer(
            "Данные для смены региона доступны в веб-приложении.",
            reply_markup=payment_moved_keyboard("appstore"),
        )
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
