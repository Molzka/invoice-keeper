"""Session-cookie client for the existing /api/v1 payment API."""

import asyncio
import ipaddress
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp


class ApiNotConfigured(Exception):
    """Missing or invalid local configuration; never includes secret values."""


class ApiUnavailable(Exception):
    """Transport or HTTP failure."""


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


def parse_payments(data, *, limit, offset):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ApiDataError("Ожидался список items с параметрами страницы")
    for key in ("total", "limit", "offset"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ApiDataError("Неверные параметры страницы")
    if data["limit"] != limit or data["offset"] != offset or len(data["items"]) > limit:
        raise ApiDataError("Сервер вернул другую страницу")
    for row in data["items"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("title"), str)
            or not 1 <= len(row["title"]) <= 200
            or not isinstance(row.get("amount"), str)
            or re.fullmatch(r"[0-9]{1,12}\.[0-9]{2}", row["amount"]) is None
            or not isinstance(row.get("currency"), str)
            or row["currency"] not in {"RUB", "USD", "EUR"}
            or not isinstance(row.get("due_date"), str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["due_date"]) is None
        ):
            raise ApiDataError("Неверные поля платежа")
        try:
            date.fromisoformat(row["due_date"])
        except ValueError:
            raise ApiDataError("Неверная дата платежа") from None
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
            address = ipaddress.ip_address(urlsplit(self._base).hostname)
            local_ip = address.is_loopback or address.is_private
        except ValueError:
            local_ip = False
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            cookie_jar=aiohttp.CookieJar(unsafe=local_ip),
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

    async def fetch_payments(self, kind, *, limit=5, offset=0):
        if kind not in {"upcoming", "overdue"}:
            raise ValueError("Неизвестный вид списка")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit должен быть от 1 до 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset должен быть неотрицательным целым")
        def params():
            today = datetime.now(self._timezone).date()
            values = {"status": "unpaid", "limit": limit, "offset": offset}
            if kind == "upcoming":
                values.update(
                    date_from=today.isoformat(), date_to=(today + timedelta(days=6)).isoformat()
                )
            else:
                values["is_overdue"] = "true"
            return values

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
                data = await self._request("GET", "/payment-occurrences", params=params())
            except _SessionExpired:
                self._authenticated = False
                await self._login()
                try:
                    data = await self._request("GET", "/payment-occurrences", params=params())
                except _SessionExpired:
                    self._auth_failed = True
                    raise ApiAuthError("Не удалось восстановить сессию бота") from None
            return parse_payments(data, limit=limit, offset=offset)

    async def close(self):
        if self._session is not None:
            await self._session.close()
        self._session = None
        self._authenticated = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.close()
