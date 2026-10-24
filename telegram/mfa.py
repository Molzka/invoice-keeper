"""Narrow service-authenticated bridge for personal Telegram enrollment."""

import asyncio
import json
import os
import re
from urllib.parse import urlsplit

import aiohttp

LINK_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class MfaBridgeError(Exception):
    """A safe public category, never an upstream body or credential."""

    def __init__(self, reason="unavailable"):
        self.reason = reason
        super().__init__(reason)


async def claim_telegram(token, *, telegram_id, chat_id, username, display_name):
    if (
        not isinstance(token, str)
        or LINK_TOKEN.fullmatch(token) is None
        or type(telegram_id) is not int
        or type(chat_id) is not int
        or telegram_id <= 0
        or telegram_id != chat_id
    ):
        raise MfaBridgeError("invalid")

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
        raise MfaBridgeError("unavailable")

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10), cookie_jar=aiohttp.DummyCookieJar()
        ) as session:
            async with session.post(
                base + "/internal/v1/telegram-auth/claim",
                json={
                    "token": token,
                    "telegram_id": telegram_id,
                    "chat_id": chat_id,
                    "username": username,
                    "display_name": display_name,
                },
                headers={"Authorization": "Bearer " + secret},
                allow_redirects=False,
            ) as response:
                if response.status in {400, 404, 409, 410, 422}:
                    raise MfaBridgeError("invalid")
                if response.status == 429:
                    raise MfaBridgeError("limited")
                if response.status != 200:
                    raise MfaBridgeError("unavailable")
                if response.content_length is not None and response.content_length > 4096:
                    raise MfaBridgeError("unavailable")
                body = bytearray()
                async for chunk in response.content.iter_chunked(1024):
                    body.extend(chunk)
                    if len(body) > 4096:
                        raise MfaBridgeError("unavailable")
                if json.loads(body) != {"accepted": True}:
                    raise MfaBridgeError("unavailable")
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError):
        raise MfaBridgeError("unavailable") from None
