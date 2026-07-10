"""
Касса Robokassa (агрегатор) — активная касса бота.

Протокол Robokassa (в отличие от прямого шлюза Альфы) простой и без серверного
API регистрации: платёж — это редирект пользователя на форму Robokassa с подписью,
а подтверждение приходит на ResultURL (services/robokassa_webhook.py).

Поток:
  1. create_payment() → создаём заказ в БД (InvId = SERIAL), собираем ссылку на
     https://auth.robokassa.ru/Merchant/Index.aspx с подписью (Пароль#1).
  2. Клиент платит на форме Robokassa.
  3. Robokassa шлёт ResultURL (GET/POST) с подписью (Пароль#2) → выдаём ключ.
  4. Robokassa редиректит клиента на SuccessURL/FailURL (настраивается в ЛК).

Подпись создания:  hash(MerchantLogin:OutSum:InvId:Пароль#1[:Receipt][:Shp_* по алфавиту])
Алгоритм хеша (md5/sha256/…) должен совпадать с настройкой в ЛК Robokassa.

Документация: https://docs.robokassa.ru/
"""
import json
import hashlib
import urllib.parse
from decimal import Decimal

from config.utils import logger
from config.config_env import (
    ROBOKASSA_MERCHANT_LOGIN, ROBOKASSA_PASSWORD1, ROBOKASSA_HASH_ALGO,
    ROBOKASSA_IS_TEST, ROBOKASSA_PAYMENT_URL, ROBOKASSA_CULTURE,
    ROBOKASSA_FISCAL, ROBOKASSA_TAX, ROBOKASSA_PAYMENT_METHOD, ROBOKASSA_PAYMENT_OBJECT,
    ROBOKASSA_SNO, ROBOKASSA_EMAIL,
)
from services.rates import RATES
from repository.database.database import create_robokassa_order


_ALGOS = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
}


def hash_signature(data: str) -> str:
    """Хеш строки подписи выбранным алгоритмом (hex, нижний регистр)."""
    algo = _ALGOS.get(ROBOKASSA_HASH_ALGO, hashlib.md5)
    return algo(data.encode("utf-8")).hexdigest()


def shp_suffix(shp: dict) -> str:
    """
    Хвост подписи из пользовательских параметров Shp_*: отсортированы по имени
    (включая префикс Shp_), каждый как ':Shp_key=value'. Тот же набор Robokassa
    вернёт в ResultURL и включит в свою подпись.
    """
    return "".join(f":{k}={shp[k]}" for k in sorted(shp))


def _format_sum(amount_rub: int) -> str:
    """OutSum строкой с двумя знаками — то же значение уходит и в подпись, и в URL."""
    return f"{Decimal(amount_rub):.2f}"


def _build_receipt(amount_rub: int) -> str:
    """
    Фискальный чек (54-ФЗ) для параметра Receipt — компактный JSON.
    ⚠️ Нужен, только если в ЛК Robokassa включена фискализация (ROBOKASSA_FISCAL).
    Компактные separators (без пробелов) убирают неоднозначность url-encode: одна и
    та же строка идёт в подпись и в URL. sno добавляем, только если задан в env
    (иначе используется система налогообложения по умолчанию из ЛК).
    """
    item = {
        "name": "Цифровой информационный материал",
        "quantity": 1,
        "sum": round(float(amount_rub), 2),
        "payment_method": ROBOKASSA_PAYMENT_METHOD,
        "payment_object": ROBOKASSA_PAYMENT_OBJECT,
        "tax": ROBOKASSA_TAX,
    }
    receipt = {"sno": ROBOKASSA_SNO, "items": [item]} if ROBOKASSA_SNO else {"items": [item]}
    return json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))


async def create_payment(amount: int, chat_id, user_id, source: str | None = None) -> tuple:
    """
    Создаёт заказ и возвращает (pay_url, inv_id). Сигнатура совместима с ЮKassa/Альфой.
    """
    amount_rub = int(RATES[amount])            # у Robokassa сумма в рублях
    inv_id = await create_robokassa_order(
        user_id=int(user_id),
        chat_id=int(chat_id),
        nominal=amount,
        amount_rub=amount_rub,
        source=source,
    )

    out_sum = _format_sum(amount_rub)

    # Пользовательские параметры (вернутся в ResultURL и войдут в подпись).
    shp = {
        "Shp_uid": str(user_id),
        "Shp_cid": str(chat_id),
        "Shp_nom": str(amount),
    }

    # Receipt (если фискализация включена) входит в подпись в URL-encoded виде.
    receipt_enc = ""
    if ROBOKASSA_FISCAL:
        receipt_enc = urllib.parse.quote(_build_receipt(amount_rub), safe="")

    # hash(MerchantLogin:OutSum:InvId[:Receipt]:Пароль#1[:Shp_*])
    sign_parts = [ROBOKASSA_MERCHANT_LOGIN, out_sum, str(inv_id)]
    if receipt_enc:
        sign_parts.append(receipt_enc)
    sign_parts.append(ROBOKASSA_PASSWORD1)
    signature = hash_signature(":".join(sign_parts) + shp_suffix(shp))

    # Собираем query вручную: Receipt уже percent-encoded, повторно не кодируем.
    params = {
        "MerchantLogin": ROBOKASSA_MERCHANT_LOGIN,
        "OutSum": out_sum,
        "InvId": str(inv_id),
        "Description": f"Оплата заказа user_id ({user_id})",
        "SignatureValue": signature,
        "Culture": ROBOKASSA_CULTURE,
        "Encoding": "utf-8",
        **shp,
    }
    if ROBOKASSA_IS_TEST:
        params["IsTest"] = "1"
    # Email получателя чека (в подпись НЕ входит). Если не задан — Robokassa
    # спросит адрес у клиента на форме оплаты.
    if ROBOKASSA_EMAIL:
        params["Email"] = ROBOKASSA_EMAIL

    query = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items()
    )
    if receipt_enc:
        query += f"&Receipt={receipt_enc}"

    pay_url = f"{ROBOKASSA_PAYMENT_URL}?{query}"
    logger.info(
        f"Robokassa: заказ InvId={inv_id} для юзера {user_id}, {out_sum}₽"
        f"{' (TEST)' if ROBOKASSA_IS_TEST else ''}"
    )
    return pay_url, inv_id
