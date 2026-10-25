"""Session-cookie client for the existing /api/v1 payment API."""

import asyncio
import ipaddress
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp


class ApiNotConfigured(Exception):
    """Missing or invalid local configuration; never includes secret values."""


class ApiUnavailable(Exception):
    """Transport or HTTP failure."""


class ApiNotFound(ApiUnavailable):
    """The requested payment occurrence no longer exists."""


class ApiDataError(Exception):
    """The response does not match the payment API contract."""


class ApiAuthError(ApiUnavailable):
    """The dedicated ordinary user's session could not be established."""


class ApiRateLimited(ApiUnavailable):
    """Wait for Retry-After before making another request."""


class _SessionExpired(Exception):
    pass


def _url(value, name, *, origin=False):
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and (not origin or parsed.path in {"", "/"})
        )
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ApiNotConfigured(f"Проверьте {name}")
    return value.rstrip("/")


def _date(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ApiDataError("Неверная календарная дата")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiDataError("Неверная календарная дата") from None


def _uuid(value):
    if not isinstance(value, str):
        raise ApiDataError("Неверный ID платежа")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ApiDataError("Неверный ID платежа") from None
    if str(parsed) != value:
        raise ApiDataError("Неверный ID платежа")
    return parsed


def parse_payment(data):
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("title"), str)
        or not 1 <= len(data["title"]) <= 200
        or not isinstance(data.get("amount"), str)
        or re.fullmatch(r"[0-9]{1,12}\.[0-9]{2}", data["amount"]) is None
        or not isinstance(data.get("currency"), str)
        or data["currency"] not in {"RUB", "USD", "EUR"}
        or not isinstance(data.get("status"), str)
        or data["status"] not in {"paid", "unpaid"}
        or "paid_on" not in data
        or type(data.get("days_late")) is not int
        or data["days_late"] < 0
        or ("is_cancelled" in data and type(data["is_cancelled"]) is not bool)
        or any(
            type(data.get(key)) is not bool
            for key in ("is_overdue", "paid_late", "recurring_payment_is_active")
        )
    ):
        raise ApiDataError("Неверные поля платежа")
    _uuid(data.get("id"))
    _uuid(data.get("recurring_payment_id"))
    due = _date(data.get("due_date"))
    if data["status"] == "paid":
        paid_on = _date(data["paid_on"])
        if data["is_overdue"] or data["paid_late"] != (paid_on > due):
            raise ApiDataError("Противоречивый статус платежа")
    elif data["paid_on"] is not None or data["paid_late"]:
        raise ApiDataError("Противоречивый статус платежа")
    return data


def parse_payments(data, *, limit, offset):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ApiDataError("Ожидался список items с параметрами страницы")
    for key in ("total", "limit", "offset"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ApiDataError("Неверные параметры страницы")
    if data["limit"] != limit or data["offset"] != offset or len(data["items"]) > limit:
        raise ApiDataError("Сервер вернул другую страницу")
    for row in data["items"]:
        parse_payment(row)
    return data


def parse_summary(data):
    if not isinstance(data, dict):
        raise ApiDataError("Неверный ответ сводки")
    start, end, today = (_date(data.get(key)) for key in ("date_from", "date_to", "as_of_date"))
    if not start <= today <= end:
        raise ApiDataError("Противоречивые даты сводки")
    try:
        ZoneInfo(data["timezone"])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise ApiDataError("Сервер не вернул корректный часовой пояс сводки") from None
    totals = data.get("totals")
    if not isinstance(totals, dict) or set(totals) != {"RUB", "USD", "EUR"}:
        raise ApiDataError("Неверные валюты сводки")
    for values in totals.values():
        if not isinstance(values, dict) or set(values) != {"planned", "paid", "unpaid", "overdue"}:
            raise ApiDataError("Неверные поля итогов сводки")
        # Aggregate totals may exceed the 12-digit limit of one payment.
        if any(
            not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]{2}", value) is None
            for value in values.values()
        ):
            raise ApiDataError("Неверная сумма сводки")
    return data


class PaymentsClient:
    """One cookie session per bot process; configuration is loaded on first use."""

    def __init__(self):
        self._session = None
        self._lock = asyncio.Lock()
        self._authenticated = False
        self._auth_failed = False
        self._retry_at = 0.0
        self._timezone = None

    def _configure(self):
        self._base = _url(os.environ.get("API_BASE_URL", "").strip(), "API_BASE_URL")
        self._origin = _url(
            os.environ.get("API_ORIGIN", "").strip(), "API_ORIGIN", origin=True
        )
        self._username = os.environ.get("API_USERNAME", "").strip()
        self._password = os.environ.get("API_PASSWORD", "")
        if not self._username or not self._password:
            raise ApiNotConfigured("Задайте API_USERNAME и API_PASSWORD")
        try:
            timeout = float(os.environ.get("API_TIMEOUT", "10"))
        except ValueError:
            timeout = 0
        if not math.isfinite(timeout) or not 1 <= timeout <= 60:
            raise ApiNotConfigured("API_TIMEOUT должен быть числом от 1 до 60")
        try:
            ipaddress.ip_address(urlsplit(self._base).hostname)
            ip_host = True
        except ValueError:
            ip_host = False
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            # The administrator configures this origin; IP cookies still obey host and Secure rules.
            cookie_jar=aiohttp.CookieJar(unsafe=ip_host),
            headers={"Accept": "application/json"},
        )

    async def _request(self, method, path, *, params=None, body=None, login=False):
        try:
            async with self._session.request(
                method,
                self._base + path,
                params=params,
                json=body,
                headers={"Origin": self._origin} if login else None,
                allow_redirects=False,
            ) as response:
                if response.status == 429:
                    try:
                        delay = max(1, int(response.headers.get("Retry-After", "60")))
                    except ValueError:
                        delay = 60
                    self._retry_at = time.monotonic() + delay
                    raise ApiRateLimited("Слишком много запросов; повторите позже")
                if login and response.status in {400, 401, 403, 422}:
                    self._auth_failed = True
                    raise ApiAuthError("Проверьте учётную запись бота и API_ORIGIN")
                if response.status == 401:
                    raise _SessionExpired
                if response.status == 404:
                    raise ApiNotFound("Период платежа не найден")
                if response.status != 200:
                    raise ApiUnavailable(f"HTTP {response.status}")
                try:
                    return await response.json()
                except (ValueError, aiohttp.ContentTypeError):
                    raise ApiDataError("Сервер вернул неверный JSON") from None
        except (asyncio.TimeoutError, aiohttp.ClientError):
            raise ApiUnavailable("Не удалось связаться с сервером платежей") from None

    async def _login(self):
        data = await self._request(
            "POST", "/auth/login", login=True,
            body={"username": self._username, "password": self._password},
        )
        if not isinstance(data, dict) or not isinstance(data.get("user"), dict):
            raise ApiDataError("Неверный ответ авторизации")
        if data["user"].get("role") != "user":
            self._session.cookie_jar.clear()
            self._auth_failed = True
            raise ApiAuthError("Для бота нужна отдельная обычная учётная запись")
        try:
            self._timezone = ZoneInfo(data["timezone"])
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
            self._session.cookie_jar.clear()
            raise ApiDataError("Сервер не вернул корректный часовой пояс") from None
        self._authenticated = True

    async def _authenticated_get(self, path, *, params_factory=None):
        async with self._lock:
            if self._auth_failed:
                raise ApiAuthError("Исправьте настройки API и перезапустите бота")
            if time.monotonic() < self._retry_at:
                raise ApiRateLimited("Слишком много запросов; повторите позже")
            if self._session is None or self._session.closed:
                self._configure()
            if not self._authenticated:
                await self._login()
            try:
                return await self._request(
                    "GET", path, params=params_factory() if params_factory else None
                )
            except _SessionExpired:
                self._authenticated = False
                await self._login()
                try:
                    return await self._request(
                        "GET", path, params=params_factory() if params_factory else None
                    )
                except _SessionExpired:
                    self._auth_failed = True
                    raise ApiAuthError("Не удалось восстановить сессию бота") from None

    async def fetch_payments(self, kind="all", *, limit=5, offset=0):
        if kind not in {"all", "upcoming", "overdue"}:
            raise ValueError("Неизвестный вид списка")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit должен быть от 1 до 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset должен быть неотрицательным целым")

        def params():
            values = {"limit": limit, "offset": offset}
            if kind != "all":
                values["status"] = "unpaid"
            if kind == "upcoming":
                today = datetime.now(self._timezone).date()
                values.update(
                    date_from=today.isoformat(), date_to=(today + timedelta(days=6)).isoformat()
                )
            elif kind == "overdue":
                values["is_overdue"] = "true"
            return values

        data = await self._authenticated_get("/payment-occurrences", params_factory=params)
        return parse_payments(data, limit=limit, offset=offset)

    async def fetch_payment(self, occurrence_id):
        if not isinstance(occurrence_id, (str, UUID)):
            raise ValueError("Нужен UUID периода платежа")
        try:
            identifier = str(UUID(str(occurrence_id)))
        except ValueError:
            raise ValueError("Нужен UUID периода платежа") from None
        data = parse_payment(await self._authenticated_get("/payment-occurrences/" + identifier))
        if data["id"] != identifier:
            raise ApiDataError("Сервер вернул другой период платежа")
        return data

    async def fetch_summary(self):
        return parse_summary(await self._authenticated_get("/payments/summary"))

    async def close(self):
        if self._session is not None:
            await self._session.close()
        self._session = None
        self._authenticated = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.close()
