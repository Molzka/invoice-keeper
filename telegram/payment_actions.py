from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from api import ApiDataError, parse_payment
from bridge import BridgeError, post_internal
from mfa import LINK_TOKEN


async def claim_payment_link(token, user):
    result = await post_internal(
        "/telegram-payments/claim",
        {
            "token": token,
            "telegram_id": user.id,
            "chat_id": user.id,
            "username": user.username,
            "display_name": user.full_name[:128],
        },
    )
    if result != {"accepted": True}:
        raise BridgeError()


async def prepare_payment(occurrence_id, user_id, chat_id):
    data = await post_internal(
        "/telegram-payments/prepare",
        {
            "occurrence_id": str(UUID(occurrence_id)),
            "telegram_id": user_id,
            "chat_id": chat_id,
        },
    )
    try:
        payment = parse_payment(data["payment"])
        if (
            payment["id"] != occurrence_id
            or not isinstance(data["token"], str)
            or LINK_TOKEN.fullmatch(data["token"]) is None
            or date.fromisoformat(data["paid_on"]).isoformat() != data["paid_on"]
            or datetime.fromisoformat(data["expires_at"]).tzinfo is None
        ):
            raise ValueError
        ZoneInfo(data["timezone"])
    except (KeyError, ValueError, TypeError, ApiDataError):
        raise BridgeError() from None
    return data


async def decide_payment(token, user_id, chat_id, *, cancel=False):
    data = await post_internal(
        "/telegram-payments/" + ("cancel" if cancel else "confirm"),
        {
            "token": token,
            "telegram_id": user_id,
            "chat_id": chat_id,
        },
    )
    if cancel:
        if data != {"accepted": True}:
            raise BridgeError()
    else:
        try:
            parse_payment(data["payment"])
            if data["outcome"] not in {"paid", "already_paid", "already_processed"}:
                raise ValueError
        except (KeyError, ValueError, TypeError, ApiDataError):
            raise BridgeError() from None
    return data
