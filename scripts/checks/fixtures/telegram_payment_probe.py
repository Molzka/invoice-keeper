"""Real Dispatcher + HTTP + PostgreSQL payment confirmation, no Telegram network."""

import asyncio
import itertools
import os
import secrets
from datetime import UTC, datetime

import bot as application
from access_security_probe import Client, require
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update
from bot_api_probe import LocalTelegram
from bridge import BridgeError


async def main():
    admin, member = Client(), Client()
    transport = LocalTelegram()
    bot = Bot(
        os.environ["BOT_TOKEN"],
        session=transport,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(application.secure)
    dispatcher.include_router(application.public)
    sequence = itertools.count(1)
    telegram_id = 987654321
    group = int(os.environ["CHAT_ID"])
    user_id = None

    async def dispatch(*, callback=None, start=None, actor=telegram_id, chat=group, is_bot=False):
        identity = {
            "id": actor,
            "is_bot": is_bot,
            "first_name": "Member <&>",
            "username": "payment_member",
        }
        message = {
            "message_id": 123,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": chat, "type": "private" if chat > 0 else "supergroup"},
        }
        data = {"update_id": next(sequence)}
        if callback:
            data["callback_query"] = {
                "id": str(next(sequence)),
                "from": identity,
                "chat_instance": "payments",
                "data": callback,
                "message": {
                    **message,
                    "text": "Payment",
                    "from": {"id": bot.id, "is_bot": True, "first_name": "Keeper"},
                },
            }
        else:
            data["message"] = {
                **message,
                "text": "/start " + start,
                "from": identity,
                "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
            }
        transport.calls.clear()
        await dispatcher.feed_update(bot, Update.model_validate(data, context={"bot": bot}))
        return list(transport.calls)

    def confirmation(calls):
        for call in calls:
            if call.__api_method__ == "sendMessage" and call.reply_markup:
                for row in call.reply_markup.inline_keyboard:
                    for button in row:
                        if button.callback_data and button.callback_data.startswith("paid:"):
                            return button.callback_data
        raise RuntimeError("No payment confirmation button")

    try:
        await admin.login(os.environ["ADMIN_USERNAME"], os.environ["ADMIN_PASSWORD"])
        username, password = "tg_pay_" + secrets.token_hex(5), secrets.token_urlsafe(24)
        user = await admin.post(
            "/users", {"username": username, "password": password}, expected=201
        )
        user_id = user["id"]
        item = await admin.post(
            "/one-time-payments",
            {
                "title": "Telegram integration <&>",
                "amount": "12.34",
                "currency": "EUR",
                "due_date": "2026-01-01",
            },
            expected=201,
        )
        await member.login(username, password)
        calls = await dispatch(callback="pay:" + item["id"])
        require(
            any(
                getattr(call, "text", None) == application.T["PAYMENT_LINK_REQUIRED"]
                for call in calls
            ),
            "Unlinked user was not denied",
        )
        await member.post("/auth/security/reauth", {"password": password})
        setup = await member.post("/auth/telegram-payments/setup")
        start = setup["link"].split("start=")[1]
        await dispatch(start=start)
        state = await member.request("/auth/telegram-payments/setup/" + setup["setup_id"])
        require(state["status"] == "waiting", "Group start claimed a private payment link")
        await dispatch(start=start, chat=telegram_id)
        state = await member.request("/auth/telegram-payments/setup/" + setup["setup_id"])
        require(
            state["account"]["id"] == str(telegram_id),
            "Wrong Telegram identity was linked",
        )
        await member.post(
            "/auth/telegram-payments/confirm",
            {"setup_id": setup["setup_id"], "telegram_id": str(telegram_id)},
        )
        require(
            not (await member.request("/auth/security"))["mfa_enabled"],
            "Payment linking enabled MFA",
        )
        print(
            "PASS: private Dispatcher linking and browser confirmation work without MFA",
            flush=True,
        )

        pay = confirmation(await dispatch(callback="pay:" + item["id"]))
        await dispatch(callback=pay, actor=telegram_id + 1)
        await dispatch(callback=pay, chat=777)
        await dispatch(callback=pay, is_bot=True)
        require(
            (await member.request("/payment-occurrences/" + item["id"]))["status"] == "unpaid",
            "Foreign identity/chat changed the period",
        )

        # The actual HTTP mutation commits, then the caller loses its result.
        decide = application.decide_payment

        async def lose_response(*args, **kwargs):
            await decide(*args, **kwargs)
            raise BridgeError()

        application.decide_payment = lose_response
        try:
            calls = await dispatch(callback=pay)
            require(
                any(
                    getattr(call, "text", None) == application.T["PAYMENT_RESULT_UNKNOWN"]
                    for call in calls
                ),
                "Response loss was presented as success",
            )
        finally:
            application.decide_payment = decide
        paid = await member.request("/payment-occurrences/" + item["id"])
        require(paid["status"] == "paid", "The real payment did not commit")
        await dispatch(callback=pay)
        events = await admin.request(
            "/audit-events?action=payment.paid&query=Telegram%20integration"
        )
        require(
            events["total"] == 1 and events["items"][0]["actor"]["id"] == user_id,
            "Replay duplicated payment or lost its actor",
        )
        await member.request(
            "/payment-occurrences/" + item["id"],
            method="PATCH",
            body={"status": "unpaid", "paid_on": None},
        )
        await dispatch(callback=pay)
        require(
            (await member.request("/payment-occurrences/" + item["id"]))["status"] == "unpaid",
            "Replay undid a later web correction",
        )
        cancel = confirmation(await dispatch(callback="pay:" + item["id"]))
        await dispatch(callback=cancel.replace("paid:", "paycancel:", 1))
        await dispatch(callback=cancel)
        require(
            (await member.request("/payment-occurrences/" + item["id"]))["status"] == "unpaid",
            "Cancelled confirmation paid the period",
        )
        await member.post("/auth/security/reauth", {"password": password})
        await member.request("/auth/telegram-payments", method="DELETE", expected=204)
        calls = await dispatch(callback="pay:" + item["id"])
        require(
            any(
                getattr(call, "text", None) == application.T["PAYMENT_LINK_REQUIRED"]
                for call in calls
            ),
            "Unlinked account still pays",
        )
        print(
            "PASS: identity/chat guards, response loss, replay, web undo, cancel and unlink preserve payment state",
            flush=True,
        )
    finally:
        if user_id:
            await admin.request("/users/" + user_id, method="DELETE", expected=204)
        await member.close()
        await admin.close()
        await application.api_client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
