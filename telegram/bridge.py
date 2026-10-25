"""Authenticated internal requests; never retry a mutation or expose upstream bodies."""

import json
import os
from urllib.parse import urlsplit

import aiohttp

SAFE_CODES = {
    "TELEGRAM_ACCOUNT_REQUIRED",
    "TELEGRAM_CHAT_DENIED",
    "TELEGRAM_CONFIRMATION_EXPIRED",
    "TELEGRAM_PAYMENT_CHANGED",
    "TELEGRAM_ALREADY_LINKED",
    "TELEGRAM_LINK_INVALID",
    "TELEGRAM_LINK_USED",
    "PAYMENT_CANCELLED",
    "PAYMENT_ALREADY_PAID",
    "PAYMENT_OCCURRENCE_NOT_FOUND",
    "ADMIN_ACCOUNT_PROTECTED",
    "MFA_CHALLENGE_EXPIRED",
    "AUTH_REQUIRED",
    "TELEGRAM_ID_CONFLICT",
}


class BridgeError(Exception):
    def __init__(self, status=0, code="BRIDGE_UNAVAILABLE"):
        self.status, self.code = status, code
        super().__init__(code)


async def post_internal(path, payload):
    base = os.environ.get("BOT_INTERNAL_BASE_URL", "http://backend:8000").rstrip("/")
    secret = os.environ.get("BOT_INTERNAL_TOKEN", "").strip()
    try:
        parsed = urlsplit(base)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not parsed.path
            and not any(char.isspace() for char in base)
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid or not secret:
        raise BridgeError()
    try:
        async with (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10), cookie_jar=aiohttp.DummyCookieJar()
            ) as session,
            session.post(
                base + "/internal/v1" + path,
                json=payload,
                headers={"Authorization": "Bearer " + secret},
                allow_redirects=False,
            ) as response,
        ):
            if response.content_length is not None and response.content_length > 4096:
                raise BridgeError(response.status)
            body = bytearray()
            async for chunk in response.content.iter_chunked(1024):
                body.extend(chunk)
                if len(body) > 4096:
                    raise BridgeError(response.status)
            try:
                data = json.loads(body)
            except (ValueError, RecursionError):
                raise BridgeError(response.status) from None
            if response.status != 200:
                error = data.get("error") if isinstance(data, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                raise BridgeError(
                    response.status,
                    code if isinstance(code, str) and code in SAFE_CODES else "BRIDGE_UNAVAILABLE",
                )
            if not isinstance(data, dict):
                raise BridgeError()
            return data
    except (TimeoutError, aiohttp.ClientError, ValueError):
        raise BridgeError() from None
