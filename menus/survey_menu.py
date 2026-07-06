"""
Опрос 2PAY после выдачи кода.

Кнопка «✍️ Пройти опрос и получить 50 ₺» появляется под сообщением с кодом
(см. services/yookassa_webhook.py). Флоу: 5 вопросов с вариантами → возможный
текст-дожим по Q5 → свободное поле (текст/фото) → отправка ответов в survey-канал
и начисление бонуса 50 ₺ (ключ с листа "50" таблицы appstore_topups).

Бонус — строго 1 на user_id (см. claim_survey_bonus): повторное прохождение
бонус не даёт и до опроса даже не пускает.
"""
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.config_env import SURVEY_CHAT_ID, ADMIN_CHAT_ID
from config.utils import logger
from repository.database.database import has_completed_survey, claim_survey_bonus
from repository.sheets.sheets import sheets, run_sheet

rt = Router()

BONUS_NOMINAL = 50            # лист "50" в appstore_topups
MSK = timezone(timedelta(hours=3))

# Вопросы с вариантами. Порядок строго как в ТЗ; текст варианта уходит в канал as-is.
QUESTIONS = [
    {
        "key": "q1",
        "prompt": "Вопрос 1 из 5. Сомневались перед покупкой?",
        "options": [
            "Боялся оплатить и не получить код",
            "Не понимал, как активировать код / сменить регион",
            "Переживал, что код не подойдёт или не сработает",
            "Незнакомый сервис — не знал, можно ли доверять",
            "Ничего не смущало, всё было понятно",
        ],
    },
    {
        "key": "q2",
        "prompt": "Вопрос 2 из 5. Насколько всё прошло понятно и удобно?",
        "options": [
            "Чётко и просто",
            "Местами пришлось разбираться",
            "Было запутанно",
        ],
    },
    {
        "key": "q3",
        "prompt": "Вопрос 3 из 5. Как сработала поддержка (бот/менеджер)?",
        "options": [
            "Быстро помогли и всё объяснили",
            "Помогли, но пришлось ждать",
            "Отвечали долго или сухо",
            "Не помогли",
            "Не обращался",
        ],
    },
    {
        "key": "q4",
        "prompt": "Вопрос 4 из 5. Что для вас было главным при выборе сервиса?",
        "options": [
            "Выгодная цена",
            "Быстро выдаёте код",
            "Доверие и отзывы",
            "Просто и удобно",
            "Посоветовали знакомые",
        ],
    },
    {
        "key": "q5",
        "prompt": "Вопрос 5 из 5. Вернётесь / порекомендуете?",
        "options": [
            "Да",
            "Возможно",
            "Нет",
        ],
    },
]

# индексы вариантов Q5 («Возможно», «Нет»), после которых спрашиваем дожим текстом
Q5_FOLLOWUP_IDX = {1, 2}


class Survey(StatesGroup):
    question = State()       # ждём выбор варианта (номер вопроса — в data["qi"])
    q5_followup = State()    # ждём текст-дожим после «Возможно/Нет»
    free = State()           # ждём свободное поле (текст/фото)


def _options_kb(qi: int):
    builder = InlineKeyboardBuilder()
    for idx, opt in enumerate(QUESTIONS[qi]["options"]):
        builder.button(text=opt, callback_data=f"sv:ans:{qi}:{idx}")
    builder.adjust(1)
    return builder.as_markup()


async def _send_question(message: Message, qi: int, state: FSMContext):
    await state.update_data(qi=qi)
    await state.set_state(Survey.question)
    await message.answer(QUESTIONS[qi]["prompt"], reply_markup=_options_kb(qi))


async def _ask_free(message: Message, state: FSMContext):
    await state.set_state(Survey.free)
    await message.answer(
        "Есть что добавить? Поделитесь — любые мысли, пожелания, замечания. "
        "Можно с фото.\n\nЕсли добавить нечего — отправьте «-»."
    )


# ---------------- старт ----------------
@rt.callback_query(F.data == "survey/start")
async def survey_start(callback: CallbackQuery, state: FSMContext):
    if await has_completed_survey(callback.from_user.id):
        await callback.answer("Вы уже проходили опрос — бонус начислен ранее 🎁", show_alert=True)
        return
    await state.clear()
    await state.update_data(answers={})
    await callback.message.answer(
        "Спасибо, что помогаете нам стать лучше! 5 коротких вопросов, "
        "и бонус 50 ₺ ваш 🎁"
    )
    await _send_question(callback.message, 0, state)
    await callback.answer()


# ---------------- ответ на вариант ----------------
@rt.callback_query(Survey.question, F.data.startswith("sv:ans:"))
async def survey_answer(callback: CallbackQuery, state: FSMContext):
    try:
        _, _, qi_s, idx_s = callback.data.split(":")
        qi, idx = int(qi_s), int(idx_s)
    except ValueError:
        await callback.answer()
        return

    data = await state.get_data()
    # клик по клавиатуре не того (уже отвеченного) вопроса — игнорируем
    if qi != data.get("qi"):
        await callback.answer()
        return

    q = QUESTIONS[qi]
    answers = data.get("answers", {})
    answers[q["key"]] = q["options"][idx]
    await state.update_data(answers=answers)

    # гасим клавиатуру, чтобы нельзя было переголосовать
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # дожим по Q5
    if q["key"] == "q5" and idx in Q5_FOLLOWUP_IDX:
        await state.set_state(Survey.q5_followup)
        await callback.message.answer("Что бы изменило ваш ответ на «да»?")
        await callback.answer()
        return

    nxt = qi + 1
    if nxt < len(QUESTIONS):
        await _send_question(callback.message, nxt, state)
    else:
        await _ask_free(callback.message, state)
    await callback.answer()


# ---------------- текст-дожим после Q5 ----------------
@rt.message(Survey.q5_followup)
async def survey_q5_followup(message: Message, state: FSMContext):
    data = await state.get_data()
    answers = data.get("answers", {})
    answers["q5_followup"] = (message.text or message.caption or "—").strip()
    await state.update_data(answers=answers)
    await _ask_free(message, state)


# ---------------- свободное поле + завершение ----------------
@rt.message(Survey.free)
async def survey_free(message: Message, state: FSMContext):
    data = await state.get_data()
    answers = data.get("answers", {})
    free_text = (message.caption or message.text or "").strip()
    if free_text == "-":
        free_text = ""
    photo_id = message.photo[-1].file_id if message.photo else None
    await _finish(message, state, answers, free_text, photo_id)


def _build_report(user, answers: dict, free_text: str) -> str:
    username = f"@{user.username}" if user.username else "—"
    name = user.full_name or "—"
    now_msk = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")

    q5_line = answers.get("q5", "—")
    if answers.get("q5_followup"):
        q5_line += f" · дожим: {answers['q5_followup']}"

    return (
        "🆕 Опрос 2PAY (после кода)\n"
        f"От: {name} {username} (id {user.id}) · {now_msk}\n"
        "─────────────\n"
        f"1. Сомнения перед покупкой: {answers.get('q1', '—')}\n"
        f"2. Понятно/удобно: {answers.get('q2', '—')}\n"
        f"3. Поддержка: {answers.get('q3', '—')}\n"
        f"4. Главное при выборе: {answers.get('q4', '—')}\n"
        f"5. Вернётся/порекомендует: {q5_line}\n"
        "─────────────\n"
        f"💬 Свободно: {free_text or '—'}"
    )


async def _finish(message: Message, state: FSMContext, answers: dict,
                  free_text: str, photo_id):
    bot = message.bot
    user = message.from_user

    # 1. ответы в survey-канал (parse_mode не ставим — текст пользователя as-is)
    report = _build_report(user, answers, free_text)
    try:
        if photo_id:
            await bot.send_photo(SURVEY_CHAT_ID, photo_id, caption=report)
        else:
            await bot.send_message(SURVEY_CHAT_ID, report)
    except Exception as e:
        logger.exception(f"[survey] не отправил ответы в канал {SURVEY_CHAT_ID}: {e}")

    # 2. бонус — атомарно, строго 1 на user_id
    if not await claim_survey_bonus(user.id):
        await message.answer("Спасибо за ответы! 🙌\n\nБонус за опрос уже был начислен ранее.")
        await state.clear()
        return

    # 3. выдаём ключ 50 ₺ с листа "50"
    key = await run_sheet(sheets.get_key, BONUS_NOMINAL)
    if key:
        await message.answer(
            f"Спасибо! Бонус 50 ₺ ваш 🎁\n\nВаш код: <code>{key}</code>",
            parse_mode="HTML",
        )
        logger.info(f"[survey] бонус 50₺ выдан юзеру {user.id}")
    else:
        # ключей нет — бонус уже «застолблён» за юзером, доставит админ вручную
        logger.error(f"[survey] нет ключей номинала {BONUS_NOMINAL} для бонуса юзеру {user.id}")
        await message.answer(
            "Спасибо! Бонус 50 ₺ закреплён за вами 🎁 — код пришлём чуть позже."
        )
        try:
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"🚨 Нет ключей 50₺ для бонуса за опрос. Выдать вручную юзеру {user.id}",
            )
        except Exception:
            logger.exception("[survey] не смог сообщить админу о нехватке ключей 50₺")

    await state.clear()
