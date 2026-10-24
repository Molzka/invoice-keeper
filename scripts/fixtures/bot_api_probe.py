"""Real Dispatcher/API scenarios; only Telegram transport is replaced locally."""

import asyncio
import html
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.types import Message, Update

import bot as application
import api as api_module


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class LocalTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise RuntimeError("Telegram downloads are forbidden")
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ == "answerCallbackQuery":
            return True
        require(
            method.__api_method__ in {"sendMessage", "editMessageText"},
            "Unexpected Telegram method",
        )
        return Message(
            message_id=123,
            date=datetime.now(UTC),
            chat={"id": int(method.chat_id), "type": "supergroup"},
            text=method.text,
        ).as_(bot)


def smoke_and_environment():
    env = dict(os.environ, BOT_TOKEN="invalid-token-for-no-send-check")
    dry_run = subprocess.run(
        [sys.executable, "/app/smoke.py", "--backend", "--dry-run", "--limit", "3"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    require(dry_run.returncode == 0, "Real API smoke dry-run failed")
    require(
        dry_run.stdout.count("Bot upcoming") == 3, "Dry-run did not render three real API records"
    )

    def sessions():
        with urlopen("http://bot-fixture:8082/sessions", timeout=5) as response:
            return json.load(response)

    before = sessions()
    for value in ("-1", "0", "101"):
        result = subprocess.run(
            [sys.executable, "/app/smoke.py", "--backend", "--limit", value],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        require(result.returncode == 2, f"Invalid smoke limit {value} was accepted")
    require(sessions() == before, "Invalid CLI limit logged into the API")
    with tempfile.TemporaryDirectory(prefix="bot-env-fixture-") as temporary:
        target = Path(temporary)
        for name in ("bot.py", "api.py", "smoke.py", "reminders.py", "formatting.py", "texts.json"):
            shutil.copyfile(Path("/app") / name, target / name)
        # Dummy file only; the real repository .env is neither mounted nor opened.
        (target / ".env").write_text(
            "CHAT_ID=123\nAPI_USERNAME=dummy_file_value\nBOT_TOKEN=dummy_file_value\n"
        )
        child_env = dict(os.environ, PYTHONPATH=str(target))
        code = (
            "import os; expected={k:os.environ[k] for k in ('CHAT_ID','API_USERNAME','BOT_TOKEN')}; "
            "import bot, smoke; assert all(os.environ[k]==v for k,v in expected.items()), 'env precedence'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=target,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        require(result.returncode == 0, "A dummy .env overrode the container environment")
    print("PASS: real-backend smoke dry-run, negative limit rejected, dummy .env precedence")


async def main():
    telegram = LocalTelegram()
    bot = Bot(
        os.environ["BOT_TOKEN"], session=telegram, default=DefaultBotProperties(parse_mode="HTML")
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(application.secure)
    dispatcher.include_router(application.public)
    sequence = itertools.count(1)
    allowed = int(os.environ["CHAT_ID"])
    api_calls = []
    real_fetch = application.api_client.fetch_payments

    async def traced_fetch(kind, **kwargs):
        # Observe calls while retaining the real HTTP client, cookies and responses.
        api_calls.append((kind, kwargs))
        return await real_fetch(kind, **kwargs)

    application.api_client.fetch_payments = traced_fetch

    async def dispatch(*, command=None, callback=None, chat=allowed):
        before = len(telegram.calls)
        message = {
            "message_id": 10,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": chat, "type": "supergroup"},
            "from": {"id": 42, "is_bot": False, "first_name": "Fixture"},
            "text": command or "Payment list",
        }
        payload = {"update_id": next(sequence)}
        if command:
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
            payload["message"] = message
        else:
            payload["callback_query"] = {
                "id": str(next(sequence)),
                "from": message["from"],
                "chat_instance": "fixture",
                "data": callback,
                "message": message,
            }
        await dispatcher.feed_update(bot, Update.model_validate(payload))
        return telegram.calls[before:]

    def check_page(calls, rows):
        messages = [
            call for call in calls if call.__api_method__ in {"sendMessage", "editMessageText"}
        ]
        require(len(messages) == 1, "Command did not render exactly one page")
        output = messages[0]
        require(
            output.text.count("\n• ") == len(rows), "Bot page size differs from the server page"
        )
        for item in rows:
            require(
                html.escape(item["title"], quote=False) in output.text,
                "Missing or unescaped API payment",
            )
        return output

    try:
        async with aiohttp.ClientSession() as fixture:

            async def control(path, method="GET"):
                async with fixture.request(method, "http://bot-fixture:8082" + path) as response:
                    require(response.status == 200, "Fixture control request failed")
                    return await response.json()

            expected = await control("/fixtures")
            # Keep real HTTP, auth and database filters, but exercise a local
            # midnight at which Tokyo and Moscow have different calendar dates.
            boundary = datetime.fromisoformat(expected["today"] + "T00:01:00").replace(
                tzinfo=ZoneInfo(expected["timezone"])
            )

            class BusinessMidnight(datetime):
                @classmethod
                def now(cls, tz=None):
                    return boundary.astimezone(tz)

            api_module.datetime = BusinessMidnight
            first = check_page(await dispatch(command="/payments"), expected["upcoming"][:5])
            session_ids = await control("/sessions")
            require(len(session_ids) == 1, "First command did not create exactly one API session")
            for page in range(1, 11):
                require(
                    first.reply_markup
                    and any(
                        button.callback_data == f"pg:upcoming:{page}"
                        for row in first.reply_markup.inline_keyboard
                        for button in row
                    ),
                    "Next-page button is missing",
                )
                first = check_page(
                    await dispatch(callback=f"pg:upcoming:{page}"),
                    expected["upcoming"][page * 5 : page * 5 + 5],
                )
            require(
                all(
                    call[1] == {"limit": 5, "offset": index * 5}
                    for index, call in enumerate(api_calls)
                ),
                "Pagination did not request bounded server pages",
            )
            check_page(await dispatch(command="/overdue"), expected["overdue"])
            require(
                any(not item["recurring_payment_is_active"] for item in expected["overdue"]),
                "Stopped unpaid history was not exercised",
            )
            require(
                await control("/sessions") == session_ids,
                "API session was not reused across commands/pages",
            )
            print(
                "PASS: /payments covers all 52 records in server pages of five; /overdue, "
                f"paid/stopped and {expected['timezone']} midnight boundary"
            )
            await control("/expire", "POST")
            check_page(await dispatch(command="/payments"), expected["upcoming"][:5])
            new_ids = await control("/sessions")
            require(
                len(new_ids) == 1 and new_ids != session_ids,
                "Expired API session did not relogin once",
            )
            print("PASS: cookie session reused, expired server session renewed")
            before = len(api_calls)
            denied = await dispatch(command="/payments", chat=allowed - 1)
            require(
                len(denied) == 1 and denied[0].text == application.T["DENIED"],
                "Foreign chat was not denied",
            )
            denied = await dispatch(callback="cmd:payments", chat=allowed - 1)
            require(
                len(denied) == 1 and denied[0].text == application.T["DENIED"],
                "Foreign callback was not denied",
            )
            await dispatch(callback="pg:upcoming:1", chat=allowed - 1)
            require(len(api_calls) == before, "Foreign chat queried payment data")
            print("PASS: foreign chat and callbacks cannot query payments")
    finally:
        await application.api_client.close()
        await bot.session.close()
    smoke_and_environment()


if __name__ == "__main__":
    asyncio.run(main())
