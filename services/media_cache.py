"""
Персистентный кэш Telegram file_id.

Проблема: бот слал фото/видео ФАЙЛАМИ (FSInputFile) на каждый вызов. На
нестабильном канале большие аплоады рвутся (ServerDisconnected на SendPhoto),
а ещё одни и те же файлы перезаливаются снова и снова, насыщая канал.

Решение: Telegram на каждую загрузку возвращает file_id (строку). Храним его
в postgres (таблица media_cache, переживает рестарты) и при повторной отправке
шлём file_id вместо файла — это текстовый запрос, а не мегабайтный upload.

Ключ = f"{bot.id}:{относительный_путь}". bot.id в ключе обязателен: file_id
привязан к токену, и тест-бот не должен подхватывать file_id боевого.
"""
from aiogram import Bot
from aiogram.types import Message, FSInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.exceptions import TelegramBadRequest

from config.utils import logger
from repository.database.database import get_file_id, set_file_id


def _key(bot: Bot, path: str) -> str:
    return f"{bot.id}:{path}"


async def send_cached_photo(message: Message, path: str, **kwargs) -> Message:
    """
    Отправить фото по file_id, если он закэширован; иначе залить файл один раз
    и сохранить file_id. Если кэшированный id протух (TelegramBadRequest) —
    перезалить и обновить кэш.
    """
    bot = message.bot
    key = _key(bot, path)

    file_id = await get_file_id(key)
    if file_id:
        try:
            return await message.answer_photo(photo=file_id, **kwargs)
        except TelegramBadRequest:
            logger.warning(f"file_id протух для {path} — перезаливаю")

    msg = await message.answer_photo(photo=FSInputFile(path), **kwargs)
    await set_file_id(key, msg.photo[-1].file_id, "photo")
    return msg


def _extras(item: dict) -> dict:
    return {k: item[k] for k in ("caption", "parse_mode") if k in item}


async def _build_item(bot: Bot, item: dict):
    file_id = await get_file_id(_key(bot, item["path"]))
    media = file_id if file_id else FSInputFile(item["path"])
    cls = InputMediaVideo if item["kind"] == "video" else InputMediaPhoto
    return cls(media=media, **_extras(item))


async def send_cached_media_group(message: Message, items: list[dict]) -> list[Message]:
    """
    items: [{path, kind: 'photo'|'video', caption?, parse_mode?}, ...]

    Собирает медиагруппу из кэшированных file_id (или свежей заливки на промахе),
    шлёт, на протухшем file_id пересобирает всю группу свежими файлами,
    и сохраняет актуальные file_id всех элементов.
    """
    bot = message.bot

    media = [await _build_item(bot, it) for it in items]
    try:
        sent = await message.answer_media_group(media)
    except TelegramBadRequest:
        # один из file_id протух — answer_media_group валит всю группу,
        # выборочно не повторить, поэтому перезаливаем всё файлами
        logger.warning("media group: протух file_id — перезаливаю всю группу")
        rebuilt = []
        for it in items:
            cls = InputMediaVideo if it["kind"] == "video" else InputMediaPhoto
            rebuilt.append(cls(media=FSInputFile(it["path"]), **_extras(it)))
        sent = await message.answer_media_group(rebuilt)

    # back-fill: сохранить file_id всех элементов (идемпотентно)
    for it, msg in zip(items, sent):
        try:
            fid = msg.video.file_id if it["kind"] == "video" else msg.photo[-1].file_id
            await set_file_id(_key(bot, it["path"]), fid, it["kind"])
        except Exception:
            logger.exception(f"media_cache: не сохранил file_id для {it['path']}")

    return sent
