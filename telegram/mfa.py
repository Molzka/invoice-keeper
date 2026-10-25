"""Narrow service-authenticated bridge for personal Telegram enrollment."""

import re

from bridge import BridgeError, post_internal

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

    try:
        result = await post_internal(
            "/telegram-auth/claim",
            {
                "token": token,
                "telegram_id": telegram_id,
                "chat_id": chat_id,
                "username": username,
                "display_name": display_name,
            },
        )
        if result != {"accepted": True}:
            raise MfaBridgeError("unavailable")
    except BridgeError as error:
        reason = (
            "invalid"
            if error.status in {400, 404, 409, 410, 422}
            else "limited"
            if error.status == 429
            else "unavailable"
        )
        raise MfaBridgeError(reason) from None
