from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.methods import SendMessage

from app.delivery.contracts import PermanentRejection, RetryableRejection
from app.delivery.telegram import TelegramSender

from .delivery_helpers import TestPaymentSource, add_payment

pytestmark = pytest.mark.asyncio
METHOD = SendMessage(chat_id=123, text="test")


@pytest.mark.parametrize(
    "error,expected",
    [
        (TelegramRetryAfter(METHOD, "retry", retry_after=120), RetryableRejection),
        (TelegramBadRequest(METHOD, "bad"), PermanentRejection),
        (TelegramForbiddenError(METHOD, "forbidden"), PermanentRejection),
        (TelegramUnauthorizedError(METHOD, "unauthorized"), PermanentRejection),
        (TelegramNetworkError(METHOD, "connection"), TelegramNetworkError),
        (TelegramServerError(METHOD, "server"), TelegramServerError),
    ],
)
async def test_sender_classifies_rejection_without_retrying_itself(delivery_db, error, expected):
    payment_id, occurrence_id = await add_payment(delivery_db)
    async with delivery_db.session_factory() as db:
        snapshot = await TestPaymentSource().occurrence(db, payment_id, occurrence_id)
    send_message = AsyncMock(side_effect=error)
    sender = TelegramSender(SimpleNamespace(send_message=send_message), 123)
    with pytest.raises(expected) as caught:
        await sender(snapshot)
    if isinstance(caught.value, RetryableRejection):
        assert caught.value.retry_after == 120
    assert send_message.await_count == 1
