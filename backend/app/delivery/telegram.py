"""One Telegram attempt; scheduling/retries belong exclusively to the worker."""

import html

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)

from app.delivery.contracts import PaymentSnapshot, PermanentRejection, RetryableRejection


def build_reminder_text(payment: PaymentSnapshot) -> str:
    title = payment.title[:200]
    return (
        "🔔 <b>Напоминание об оплате</b>\n"
        f"Название: {html.escape(title, quote=False)}\n"
        f"Сумма: {payment.amount:.2f} {html.escape(payment.currency, quote=False)}\n"
        f"Срок: {payment.due_date.isoformat()}"
    )


class TelegramSender:
    def __init__(self, bot: Bot, chat_id: str | int):
        self.bot, self.chat_id = bot, chat_id

    async def __call__(self, payment: PaymentSnapshot) -> int:
        try:
            message = await self.bot.send_message(
                chat_id=self.chat_id, text=build_reminder_text(payment), parse_mode="HTML"
            )
        except TelegramRetryAfter as exc:
            raise RetryableRejection(exc.retry_after) from None
        except (
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramNotFound,
            TelegramUnauthorizedError,
        ):
            raise PermanentRejection() from None
        return message.message_id
