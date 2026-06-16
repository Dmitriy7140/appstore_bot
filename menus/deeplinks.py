"""
Реестр deep-link'ов: payload из `t.me/Bot?start=<payload>` → функция-отправитель меню.

Идея: payload ссылки сравнивается с callback_data кнопки. Если совпало — бот
первым же сообщением показывает соответствующее меню (а не главное меню).

Каждый обработчик принимает Message (чат, куда слать) и сам всё отправляет.
Чтобы добавить новую ссылку — вынеси нужное меню в функцию, принимающую Message,
и допиши строку в DEEPLINK_MENUS: ключ = callback_data кнопки.
"""
from aiogram.types import Message

from menus.faqs import send_region_faq, send_questions_faq
from menus.referal_menu import send_ref_menu


async def _send_ref(message: Message):
    # по deep-link отправитель /start и есть пользователь → message.from_user.id корректен
    await send_ref_menu(message, message.from_user.id)


# callback_data кнопки  ->  функция, показывающая её меню по Message
DEEPLINK_MENUS = {
    "asfaq_region": send_region_faq,
    "asfaq_questions": send_questions_faq,
    "asref": _send_ref,
}


async def handle_deeplink(message: Message, payload: str) -> bool:
    """Если payload совпал с ссылкой из реестра — показывает меню и возвращает True."""
    handler = DEEPLINK_MENUS.get(payload)
    if handler is None:
        return False
    await handler(message)
    return True
