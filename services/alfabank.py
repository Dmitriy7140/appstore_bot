"""
Касса Альфа-Банка (интернет-эквайринг, «Платёжный шлюз» / REST API RBS).

Заменяет ЮKassa (services/payments.py, теперь в спящем режиме). Тонкий async-клиент
поверх aiohttp — официального Python-SDK у Альфы нет, а REST тривиален
(form-urlencoded POST → JSON). Сторонние обёртки в денежный путь не тянем.

Поток одностадийной оплаты (аналог capture=True у ЮKassa):
  1. create_payment() → register.do → получаем formUrl (ссылка на форму банка)
     и orderId (mdOrder). Контекст заказа (кому выдать ключ) кладём в БД, т.к.
     callback шлюза его не несёт.
  2. Клиент платит на форме банка.
  3. Шлюз шлёт callback (GET) → services/alfabank_webhook.py.
  4. Вебхук перепроверяет заказ через getOrderStatusExtended.do и выдаёт ключ.

Документация: https://alfabank.ru/sme/payservice/internet-acquiring/docs/
"""
import json
import uuid

import aiohttp

from config.utils import logger
from config.config_env import (
    ALFA_API_BASE, ALFA_TOKEN, ALFA_USERNAME, ALFA_PASSWORD,
    ALFA_RETURN_URL, ALFA_FAIL_URL, ALFA_CURRENCY,
    ALFA_FISCAL, ALFA_RECEIPT_EMAIL, ALFA_TAX_TYPE, ALFA_MEASURE,
)
from services.rates import RATES
from repository.database.database import create_alfa_order


class AlfaError(Exception):
    """Шлюз вернул errorCode != 0 или сетевую ошибку при регистрации заказа."""


def _auth_params() -> dict:
    """Аутентификация: либо token, либо пара userName/password."""
    if ALFA_TOKEN:
        return {"token": ALFA_TOKEN}
    return {"userName": ALFA_USERNAME, "password": ALFA_PASSWORD}


def _api_url(method: str) -> str:
    # ALFA_API_BASE оканчивается на .../payment/rest/
    return f"{ALFA_API_BASE.rstrip('/')}/{method}"


async def _api_post(method: str, params: dict) -> dict:
    """
    POST на метод шлюза (application/x-www-form-urlencoded) → распарсенный JSON.
    Явный таймаут: платёжный путь не должен виснуть (как это делал requests без
    таймаута у ЮKassa/gspread — см. комментарий в main.py).
    """
    payload = {**_auth_params(), **params}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(_api_url(method), data=payload) as resp:
            text = await resp.text()
            try:
                return json.loads(text)
            except (ValueError, json.JSONDecodeError):
                raise AlfaError(
                    f"{method}: не-JSON ответ (HTTP {resp.status}): {text[:200]}"
                )


def _build_order_bundle(nominal: int, amount_kopecks: int) -> str:
    """
    Фискальный чек (54-ФЗ) для передачи в orderBundle.

    ⚠️ Включается флагом ALFA_FISCAL. Если Альфа фискализирует оплаты на своей
    стороне (через подключённую ОФД) — держите ALFA_FISCAL=False, тогда чек не
    отправляется. Схему/ставку НДС и признак предмета расчёта сверьте с Альфой:
    неверный orderBundle приведёт к отказу register.do и сломает ВСЕ оплаты.

    taxType Альфы: 0 — без НДС, 1 — 0%, 2 — 10%, 3 — 18%, 6 — 20% (уточните).
    """
    item = {
        "positionId": 1,
        "name": "Цифровой информационный материал",
        "quantity": {"value": 1, "measure": ALFA_MEASURE},
        "itemAmount": amount_kopecks,
        "itemCode": f"digital-{nominal}",
        "itemPrice": amount_kopecks,
        "tax": {"taxType": ALFA_TAX_TYPE},
    }
    bundle = {"cartItems": {"items": [item]}}
    if ALFA_RECEIPT_EMAIL:
        bundle["customerDetails"] = {"email": ALFA_RECEIPT_EMAIL}
    return json.dumps(bundle, ensure_ascii=False)


async def create_payment(amount: int, chat_id, user_id, source: str | None = None) -> tuple:
    """
    Регистрирует одностадийный платёж и возвращает (form_url, order_number).

    Сигнатура совместима с ЮKassa create_payment: второй элемент — идентификатор
    заказа (у Альфы это НАШ orderNumber; mdOrder шлюза узнаём позже из callback).
    """
    order_number = uuid.uuid4().hex            # уникален, <=36 символов
    amount_kopecks = int(round(RATES[amount] * 100))

    # Контекст кладём ДО регистрации: callback может прийти раньше, чем мы вернём
    # управление, и вебхуку нужно знать, кому выдавать ключ.
    await create_alfa_order(
        order_number=order_number,
        user_id=int(user_id),
        chat_id=int(chat_id),
        nominal=amount,
        amount_kopecks=amount_kopecks,
        source=source,
    )

    params = {
        "orderNumber": order_number,
        "amount": amount_kopecks,
        "currency": ALFA_CURRENCY,
        "returnUrl": ALFA_RETURN_URL,
        "failUrl": ALFA_FAIL_URL or ALFA_RETURN_URL,
        "description": f"Оплата заказа user_id ({user_id})",
        # jsonParams виден в getOrderStatusExtended — дублируем контекст на случай
        # разбора вручную/сверки. Основной источник истины всё же alfa_orders.
        "jsonParams": json.dumps({
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "nominal": str(amount),
        }),
    }
    if ALFA_FISCAL:
        params["orderBundle"] = _build_order_bundle(amount, amount_kopecks)

    try:
        data = await _api_post("register.do", params)
    except AlfaError:
        await _delete_orphan_order(order_number)
        raise

    error_code = str(data.get("errorCode", "0"))
    if error_code not in ("0", "", "None"):
        await _delete_orphan_order(order_number)
        raise AlfaError(
            f"register.do errorCode={error_code}: {data.get('errorMessage')}"
        )

    form_url = data.get("formUrl")
    md_order = data.get("orderId")
    if not form_url:
        await _delete_orphan_order(order_number)
        raise AlfaError(f"register.do без formUrl: {data}")

    logger.info(
        f"Альфа: зарегистрировали заказ {order_number} "
        f"(mdOrder={md_order}) для юзера {user_id}, {amount_kopecks} коп."
    )
    return form_url, order_number


async def get_order_status(order_id: str | None = None, order_number: str | None = None) -> dict:
    """
    Серверная перепроверка статуса заказа (getOrderStatusExtended.do).

    Возвращает распарсенный JSON. Ключевые поля:
      orderStatus: 0 — зарегистрирован, не оплачен; 1 — захолдирован (двухстадийная);
                   2 — ПОЛНОСТЬЮ ОПЛАЧЕН (успех одностадийной); 3 — отменён;
                   4 — возврат; 6 — отклонён.
      amount:      сумма в копейках; actionCode: код результата операции.
    """
    params = {}
    if order_id:
        params["orderId"] = order_id
    if order_number:
        params["orderNumber"] = order_number
    return await _api_post("getOrderStatusExtended.do", params)


async def _delete_orphan_order(order_number: str):
    """Подчистить осиротевший заказ, если register.do не удался."""
    try:
        from repository.database.database import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM alfa_orders WHERE order_number = $1", order_number
            )
    except Exception:
        logger.exception(f"Не смог удалить осиротевший заказ {order_number}")
