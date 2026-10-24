"""Запросы к бэкенду за платежами. Общий код для bot.py и smoke.py.

Настройки (читаются из окружения при каждом запросе):
  API_BASE_URL       обязателен, например http://backend:8000 (в Docker не localhost)
  API_TOKEN          необязателен, уходит как Authorization: Bearer <токен>
  API_TIMEOUT        секунды, по умолчанию 10
  API_UPCOMING_PATH  путь для платежей на 7 дней (по умолчанию /payments/upcoming?days=7)
  API_OVERDUE_PATH   путь для просроченных (по умолчанию /payments/overdue)

Ожидаемый ответ: список объектов или объект со списком в ключе
items / payments / data / results. Поля платежа: title, amount, currency, due_date
(необязательно payment_url). Лишние поля игнорируются.
"""
import asyncio
import logging
import os

import aiohttp

log = logging.getLogger("api")

REQUIRED_FIELDS = ("title", "amount", "currency", "due_date")
LIST_KEYS = ("items", "payments", "data", "results")
DEFAULT_PATHS = {
    "upcoming": "/payments/upcoming?days=7",
    "overdue": "/payments/overdue",
}


class ApiNotConfigured(Exception):
    """API_BASE_URL не задан или неверен."""


class ApiUnavailable(Exception):
    """Сеть, таймаут, HTTP 4xx/5xx."""


class ApiDataError(Exception):
    """Ответ получен, но формат не соответствует ожидаемому."""


def _settings(kind: str):
    if kind not in DEFAULT_PATHS:
        raise ValueError(f"Неизвестный вид списка: {kind!r}")
    base = os.environ.get("API_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise ApiNotConfigured("API_BASE_URL не задан")
    if not base.lower().startswith(("http://", "https://")):
        raise ApiNotConfigured("API_BASE_URL должен начинаться с http:// или https://")

    path = os.environ.get(f"API_{kind.upper()}_PATH", "").strip() or DEFAULT_PATHS[kind]
    if not path.startswith("/"):
        path = "/" + path

    token = os.environ.get("API_TOKEN", "").strip()
    try:
        timeout = float(os.environ.get("API_TIMEOUT", "10"))
    except ValueError:
        timeout = 10.0
    return base + path, token, timeout


def parse_payments(data) -> list[dict]:
    """Проверяет ответ бэкенда и оставляет только нужные поля."""
    if isinstance(data, dict):
        for key in LIST_KEYS:
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            raise ApiDataError("ответ — объект без списка платежей")
    if not isinstance(data, list):
        raise ApiDataError("ответ не является списком")

    result = []
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise ApiDataError(f"элемент {i} не является объектом")
        missing = [f for f in REQUIRED_FIELDS if row.get(f) in (None, "")]
        if missing:
            raise ApiDataError(f"элемент {i}: нет полей {missing}")
        item = {f: row[f] for f in REQUIRED_FIELDS}
        if row.get("payment_url"):
            item["payment_url"] = row["payment_url"]
        result.append(item)
    return result


async def fetch_payments(kind: str) -> list[dict]:
    """kind: 'upcoming' (7 дней) или 'overdue'.

    Одна попытка запроса. Исключения: ApiNotConfigured, ApiUnavailable, ApiDataError.
    В логи не попадают токен и содержимое ответа.
    """
    url, token, timeout = _settings(kind)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout), headers=headers
        ) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    raise ApiUnavailable(f"HTTP {resp.status}")
                try:
                    data = await resp.json(content_type=None)
                except ValueError as exc:  # включая JSONDecodeError
                    raise ApiDataError("ответ не является JSON") from exc
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        raise ApiUnavailable(type(exc).__name__) from exc

    return parse_payments(data)
