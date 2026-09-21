from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config.utils import IsAdmin


router = Router()

ADMIN_HELP = (
    "📋 <b>Шпаргалка администратора</b>\n\n"
    "/start — открыть главное меню и выйти из текущей настройки.\n"
    "/help — показать эту шпаргалку.\n\n"
    "/announce — отправить рассылку сейчас или настроить еженедельные посты: "
    "день, время, аудитория, кнопки и акции. Пересекающиеся рассылки идут по очереди.\n"
    "/menulink — создать ссылку на раздел меню с названием источника.\n\n"
    "/allusers — количество всех, оплативших и не оплативших пользователей.\n"
    "/codes — свободные коды App Store на складе.\n"
    "/salesreport — сводка продаж сайта и ТМА за последний завершённый день.\n\n"
    "/broke — включить или выключить режим обслуживания: кнопки направляют к менеджеру.\n"
    "/test10 — устаревшая тестовая команда; оплаты в боте отключены.\n\n"
    "После /help можно продолжить текущую настройку."
)


@router.message(Command("help"), IsAdmin())
async def admin_help(message: Message) -> None:
    await message.answer(ADMIN_HELP, parse_mode="HTML")


@router.message(Command("help"))
async def user_help(message: Message) -> None:
    await message.answer(
        "/start — открыть главное меню.\n"
        "/help — показать справку.\n\n"
        "Вопросы по покупке — @MANAGER_2PAY."
    )
