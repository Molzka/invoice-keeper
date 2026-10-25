"""Replay local PANEL_URL navigation with Telegram URL validation and no network sends."""

import asyncio
import io
import logging
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Update


async def main():
    os.environ["CHAT_ID"] = "-1001234567890"
    os.environ["PANEL_URL"] = "http://localhost:8080"
    import bot as application
    import reminders
    from bot_api_probe import LocalTelegram, require

    transport = LocalTelegram()
    bot = Bot(
        "123456789:" + "A" * 35, session=transport, default=DefaultBotProperties(parse_mode="HTML")
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(application.secure)
    dispatcher.include_router(application.public)
    item = {
        "id": str(UUID(int=1)),
        "recurring_payment_id": str(UUID(int=2)),
        "title": "Local panel payment <&>",
        "amount": "1.00",
        "currency": "RUB",
        "due_date": "2026-10-25",
        "status": "unpaid",
        "paid_on": None,
        "is_overdue": False,
        "paid_late": False,
        "days_late": 0,
        "recurring_payment_is_active": True,
    }
    application.api_client.fetch_payment = AsyncMock(return_value=item)
    application.prepare_payment = AsyncMock(
        return_value={
            "token": "A" * 43,
            "payment": item,
            "paid_on": "2026-10-25",
            "timezone": "Europe/Moscow",
        }
    )
    application.decide_payment = AsyncMock(
        return_value={
            "outcome": "paid",
            "payment": {**item, "status": "paid", "paid_on": "2026-10-25"},
        }
    )
    try:
        for index, data in enumerate(
            (
                "cmd:start",
                "cmd:site",
                "cmd:help",
                "cmd:id",
                "card:" + item["id"],
                "pay:" + item["id"],
                "paid:" + "A" * 43,
            ),
            1,
        ):
            transport.calls.clear()
            update = Update.model_validate(
                {
                    "update_id": index,
                    "callback_query": {
                        "id": str(index),
                        "from": {"id": 123, "is_bot": False, "first_name": "Member"},
                        "chat_instance": "local-panel",
                        "data": data,
                        "message": {
                            "message_id": 10,
                            "date": int(datetime.now(UTC).timestamp()),
                            "chat": {"id": application.ALLOWED_CHAT, "type": "supergroup"},
                            "text": "Existing message",
                        },
                    },
                },
                context={"bot": bot},
            )
            await dispatcher.feed_update(bot, update)
            messages = [
                call
                for call in transport.calls
                if call.__api_method__ in {"sendMessage", "editMessageText"}
            ]
            require(bool(messages), "Callback did not produce a visible response")
            if data.startswith("card:"):
                buttons = [
                    button for row in messages[-1].reply_markup.inline_keyboard for button in row
                ]
                require(
                    any(button.callback_data == "pay:" + item["id"] for button in buttons),
                    "Unpaid card lost its payment button",
                )
            if data == "cmd:site":
                require(
                    "localhost:8080" in messages[-1].text,
                    "Local panel instructions lost the address",
                )
        markup = reminders.build_keyboard("http://localhost:8080/#payments")
        require(
            markup is None
            or all(not button.url for row in markup.inline_keyboard for button in row),
            "Smoke reminders still emit local URL buttons",
        )
        os.environ["PANEL_URL"] = "https://panel.example.org/app"
        require(
            application.panel_button().url == os.environ["PANEL_URL"],
            "Network panel URL lost its direct button",
        )
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        application.log.addHandler(handler)
        try:
            await application.on_error(
                SimpleNamespace(
                    exception=TelegramBadRequest(
                        method=SendMessage(chat_id=1, text="private-payment-text"),
                        message="Inline keyboard button URL is invalid: Wrong HTTP URL token=never-log-this",
                    )
                )
            )
        finally:
            application.log.removeHandler(handler)
        require(
            "invalid_button_url" in output.getvalue(), "BadRequest diagnostics lost the safe reason"
        )
        require(
            "never-log-this" not in output.getvalue()
            and "private-payment-text" not in output.getvalue(),
            "Diagnostics leaked request or error contents",
        )
        print(
            "PASS: menu, site, card, payment preview/result and smoke stay usable with localhost; network URLs retain direct buttons"
        )
    finally:
        await bot.session.close()
        await application.api_client.close()


if __name__ == "__main__":
    asyncio.run(main())
