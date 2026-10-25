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
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

import aiohttp
import api as api_module
import bot as application
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, Update
from formatting import format_amount, format_date


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class TelegramMarkup(HTMLParser):
    """Validate the HTML actually emitted by handlers at the transport boundary."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.visible = []

    def handle_starttag(self, tag, attrs):
        require(
            tag
            in {
                "b",
                "strong",
                "i",
                "em",
                "u",
                "ins",
                "s",
                "strike",
                "del",
                "code",
                "pre",
                "a",
                "span",
                "tg-spoiler",
                "blockquote",
            },
            "Handler emitted an unsupported HTML tag",
        )
        self.tags.append(tag)

    def handle_endtag(self, tag):
        require(self.tags and self.tags.pop() == tag, "Handler emitted unbalanced HTML")

    def handle_data(self, data):
        self.visible.append(data)


class LocalTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.edit_error = None
        self.answer_error = None

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise RuntimeError("Telegram downloads are forbidden")
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ == "answerCallbackQuery":
            if self.answer_error:
                error, self.answer_error = self.answer_error, None
                raise TelegramBadRequest(method=method, message=error)
            return True
        require(
            method.__api_method__ in {"sendMessage", "editMessageText"},
            "Unexpected Telegram method",
        )
        markup = TelegramMarkup()
        markup.feed(method.text)
        markup.close()
        require(not markup.tags, "Handler left an HTML tag open")
        require(
            len("".join(markup.visible).encode("utf-16-le")) // 2 <= 4096,
            "Handler output exceeds Telegram's message limit",
        )
        if method.reply_markup:
            for row in method.reply_markup.inline_keyboard:
                for button in row:
                    if button.callback_data:
                        require(
                            len(button.callback_data.encode()) <= 64,
                            "Callback exceeds Telegram's byte limit",
                        )
        if method.__api_method__ == "editMessageText" and self.edit_error:
            error, self.edit_error = self.edit_error, None
            raise TelegramBadRequest(method=method, message=error)
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
    local = subprocess.run(
        [sys.executable, "/app/smoke.py"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    require(
        local.returncode == 0 and local.stdout.count("--- ") == 5,
        "Default smoke did not render all local cases without Telegram",
    )
    require(sessions() == before, "Local smoke unexpectedly contacted the API")
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
        temporary_root = Path(temporary)
        target = temporary_root / "telegram"
        target.mkdir()
        for name in (
            "bot.py",
            "api.py",
            "mfa.py",
            "bridge.py",
            "payment_actions.py",
            "smoke.py",
            "reminders.py",
            "formatting.py",
            "features.py",
            "texts.json",
        ):
            shutil.copyfile(Path("/app") / name, target / name)
        # Dummy file only; the real repository .env is neither mounted nor opened.
        (temporary_root / ".env").write_text(
            "CHAT_ID=123\nAPI_USERNAME=dummy_file_value\nBOT_TOKEN=dummy_file_value\n"
            "BOT_PROBE_ENV_SENTINEL=from-root-fixture\n"
        )
        child_env = dict(os.environ, PYTHONPATH=str(target))
        child_env.pop("BOT_PROBE_ENV_SENTINEL", None)
        code = (
            "import os; expected={k:os.environ[k] for k in ('CHAT_ID','API_USERNAME','BOT_TOKEN')}; "
            "import bot, smoke; assert all(os.environ[k]==v for k,v in expected.items()), 'env precedence'; "
            "assert os.getenv('BOT_PROBE_ENV_SENTINEL')=='from-root-fixture', 'root env location'"
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
    alias = subprocess.run(
        [sys.executable, "/app/smoke.py", "--from-api", "--limit", "3"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    require(
        alias.returncode == 0 and alias.stdout.count("Bot upcoming") == 3,
        "API smoke alias did not default to no-send output",
    )
    print(
        "PASS: local/API smoke default to no-send, dry-run/alias, bounded limits and env precedence"
    )


async def main():
    # The local proxy forwards every normal request, including login and cookies,
    # to the real API. Its explicit one-shot HTTP failure exercises retry UX.
    os.environ["API_BASE_URL"] = "http://bot-fixture:8082/api/v1"
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
    callback_start = None
    real_fetch = application.api_client.fetch_payments

    def require_ack_before_api():
        if callback_start is not None:
            require(
                any(
                    call.__api_method__ == "answerCallbackQuery"
                    for call in telegram.calls[callback_start:]
                ),
                "Callback queried the API before acknowledging the button",
            )

    async def traced_fetch(kind, **kwargs):
        # Observe calls while retaining the real HTTP client, cookies and responses.
        require_ack_before_api()
        api_calls.append((kind, kwargs))
        return await real_fetch(kind, **kwargs)

    application.api_client.fetch_payments = traced_fetch
    other_calls = []
    real_detail = application.api_client.fetch_payment
    real_summary = application.api_client.fetch_summary

    async def traced_detail(occurrence_id):
        require_ack_before_api()
        other_calls.append(("card", str(occurrence_id)))
        return await real_detail(occurrence_id)

    async def traced_summary():
        require_ack_before_api()
        other_calls.append(("summary",))
        return await real_summary()

    application.api_client.fetch_payment = traced_detail
    application.api_client.fetch_summary = traced_summary

    async def dispatch(
        *, command=None, callback=None, chat=allowed, inaccessible=False, inline=False
    ):
        nonlocal callback_start
        before = len(telegram.calls)
        callback_start = before if callback is not None else None
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
            if inaccessible:
                payload["callback_query"]["message"] = {
                    "message_id": 10,
                    "date": 0,
                    "chat": message["chat"],
                }
            if inline:
                payload["callback_query"].pop("message")
                payload["callback_query"]["inline_message_id"] = "expired-inline-fixture"
        try:
            await dispatcher.feed_update(bot, Update.model_validate(payload))
        finally:
            callback_start = None
            if callback is not None:
                calls = telegram.calls[before:]
                require(
                    sum(call.__api_method__ == "answerCallbackQuery" for call in calls) == 1,
                    "Each callback must be acknowledged exactly once",
                )
                require(
                    calls[0].__api_method__ == "answerCallbackQuery",
                    "Callback acknowledgement was delayed",
                )
        return telegram.calls[before:]

    def callbacks(message):
        return (
            [
                button.callback_data
                for row in message.reply_markup.inline_keyboard
                for button in row
                if button.callback_data
            ]
            if message.reply_markup
            else []
        )

    def output_message(calls, method=None):
        messages = [
            call for call in calls if call.__api_method__ in {"sendMessage", "editMessageText"}
        ]
        require(len(messages) == 1, "Handler did not render exactly one message")
        output = messages[0]
        if method:
            require(
                output.__api_method__ == method, "Handler used the wrong message navigation method"
            )
        if output.__api_method__ == "editMessageText":
            require(output.message_id == 10, "Navigation edited a different message")
        return output

    def check_page(calls, rows, kind=None, page=0, method=None):
        output = output_message(calls, method)
        card_buttons = [
            button
            for row in output.reply_markup.inline_keyboard
            for button in row
            if button.callback_data and button.callback_data.startswith("card:")
        ]
        card_ids = [button.callback_data.split(":")[1] for button in card_buttons]
        require(
            card_ids == [item["id"] for item in rows],
            "Card buttons do not match the bounded API page and its stable UUIDs",
        )
        for item, button in zip(rows, card_buttons):
            require(
                html.escape(item["title"], quote=False) in output.text,
                "Missing or unescaped API payment",
            )
            require(item["title"][:8] in button.text, "Card button has no readable payment title")
            if len(item["title"]) == 200:
                require(
                    len(button.text) < len(item["title"]),
                    "Card button did not shorten a long title",
                )
            blocks = [
                block
                for block in output.text.split("\n\n")
                if html.escape(item["title"], quote=False) in block
            ]
            require(
                len(blocks) == 1 and len(blocks[0].splitlines()) == 3,
                "Payment list item is not a compact three-line summary",
            )
            if kind:
                require(
                    button.callback_data == f"card:{item['id']}:{kind}:{page}",
                    "Card callback lost its list/page context",
                )
        if kind:
            require(f"pg:{kind}:{page}" in callbacks(output), "List refresh lost its current page")
        require("cmd:start" in callbacks(output), "List has no main-menu navigation")
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
            before_public = (len(api_calls), len(other_calls))
            for command in ("/start", "/menu", "/help"):
                own_menu = output_message(await dispatch(command=command), "sendMessage")
                if command != "/help":
                    require("cmd:all" in callbacks(own_menu), "Allowed chat has no financial menu")
                foreign_menu = output_message(
                    await dispatch(command=command, chat=allowed - 1), "sendMessage"
                )
                require(
                    not set(callbacks(foreign_menu))
                    & {"cmd:all", "cmd:payments", "cmd:overdue", "cmd:summary"},
                    "Public menu exposes financial buttons in another chat",
                )
            for callback in ("cmd:start", "cmd:help", "cmd:id", "cmd:site"):
                output_message(await dispatch(callback=callback), "editMessageText")
            foreign_menu = output_message(
                await dispatch(callback="cmd:start", chat=allowed - 1), "editMessageText"
            )
            require(
                not set(callbacks(foreign_menu))
                & {"cmd:all", "cmd:payments", "cmd:overdue", "cmd:summary"},
                "Foreign menu callback exposes financial buttons",
            )
            require(
                (len(api_calls), len(other_calls)) == before_public,
                "Public menu queried financial data",
            )
            first = check_page(
                await dispatch(command="/payments"),
                expected["upcoming"][:5],
                "upcoming",
                method="sendMessage",
            )
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
                    "upcoming",
                    page,
                    "editMessageText",
                )
            require(
                all(
                    call[1] == {"limit": 5, "offset": index * 5}
                    for index, call in enumerate(api_calls)
                ),
                "Pagination did not request bounded server pages",
            )
            check_page(
                await dispatch(command="/overdue"),
                expected["overdue"],
                "overdue",
                method="sendMessage",
            )
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
            check_page(
                await dispatch(command="/payments"),
                expected["upcoming"][:5],
                "upcoming",
                method="sendMessage",
            )
            new_ids = await control("/sessions")
            require(
                len(new_ids) == 1 and new_ids != session_ids,
                "Expired API session did not relogin once",
            )
            print("PASS: cookie session reused, expired server session renewed")
            check_page(
                await dispatch(command="/all"), expected["all"][:5], "all", method="sendMessage"
            )
            for page in range(1, (len(expected["all"]) + 4) // 5):
                check_page(
                    await dispatch(callback=f"pg:all:{page}"),
                    expected["all"][page * 5 : page * 5 + 5],
                    "all",
                    page,
                    "editMessageText",
                )
            require(
                any(item["status"] == "paid" for item in expected["all"]),
                "All-list did not exercise paid obligations",
            )
            require(
                any(not item["recurring_payment_is_active"] for item in expected["all"]),
                "All-list did not exercise stopped obligations",
            )
            require(
                any(
                    item["due_date"] > expected["upcoming"][-1]["due_date"]
                    for item in expected["all"]
                ),
                "All-list did not exercise dates outside the upcoming window",
            )
            require(
                all(
                    kwargs == {"limit": 5, "offset": index * 5}
                    for index, (_, kwargs) in enumerate(
                        call for call in api_calls if call[0] == "all"
                    )
                ),
                "All-list did not use bounded server pagination",
            )
            summary_calls = await dispatch(command="/summary")
            summary_messages = [
                call for call in summary_calls if call.__api_method__ == "sendMessage"
            ]
            require(len(summary_messages) == 1, "Summary did not render one API result")
            summary_text = summary_messages[0].text
            for currency, totals in expected["summary"]["totals"].items():
                require(currency in summary_text, "Summary omitted a currency")
                for amount in totals.values():
                    require(
                        html.escape(format_amount(amount, currency), quote=False) in summary_text,
                        "Summary differs from the real API's per-currency totals",
                    )
            require(
                format_date(expected["summary"]["as_of_date"]) in summary_text,
                "Summary omitted the API as-of date",
            )
            require(
                {"cmd:summary", "cmd:start"} <= set(callbacks(summary_messages[0])),
                "Summary omitted refresh or main menu",
            )
            refreshed_summary = output_message(
                await dispatch(callback="cmd:summary"), "editMessageText"
            )
            require(
                refreshed_summary.text == summary_text, "Summary refresh changed unchanged API data"
            )
            print(
                "PASS: /all keeps paid/stopped/outside-window records; monthly summary uses real currency totals"
            )

            for callback, kind in (
                ("cmd:payments", "upcoming"),
                ("cmd:overdue", "overdue"),
                ("cmd:all", "all"),
            ):
                check_page(
                    await dispatch(callback=callback),
                    expected[kind][:5],
                    kind,
                    method="editMessageText",
                )
            second_page = check_page(
                await dispatch(callback="pg:upcoming:1"),
                expected["upcoming"][5:10],
                "upcoming",
                1,
                "editMessageText",
            )
            contextual = next(
                value for value in callbacks(second_page) if value.startswith("card:")
            )
            card = output_message(await dispatch(callback=contextual), "editMessageText")
            require(
                {contextual, "pg:upcoming:1", "cmd:start"} <= set(callbacks(card)),
                "Card omitted refresh, original page or menu",
            )
            refreshed_card = output_message(await dispatch(callback=contextual), "editMessageText")
            require(refreshed_card.text == card.text, "Card refresh changed unchanged API data")
            check_page(
                await dispatch(callback="pg:upcoming:1"),
                expected["upcoming"][5:10],
                "upcoming",
                1,
                "editMessageText",
            )
            html_item = next(item for item in expected["upcoming"] if len(item["title"]) == 200)
            html_card = output_message(
                await dispatch(callback=f"card:{html_item['id']}:upcoming:0"), "editMessageText"
            )
            require(
                html.escape(html_item["title"], quote=False) in html_card.text,
                "Full 200-character Unicode/HTML title was lost in a card",
            )
            print(
                "PASS: menu/list/card/back/refresh edit the original message, preserve context and escape full titles"
            )

            for failure in (
                "Bad Request: message is not modified",
                "Bad Request: message to edit not found",
                "Bad Request: message can't be edited",
            ):
                telegram.edit_error = failure
                calls = await dispatch(callback="cmd:summary")
                edits = [call for call in calls if call.__api_method__ == "editMessageText"]
                sends = [call for call in calls if call.__api_method__ == "sendMessage"]
                require(
                    len(edits) == 1 and telegram.edit_error is None, "Edit error was not exercised"
                )
                if "not modified" in failure:
                    require(not sends, "Unchanged message caused a duplicate send")
                else:
                    require(
                        len(sends) == 1
                        and sends[0].text == edits[0].text
                        and callbacks(sends[0]) == callbacks(edits[0]),
                        "Unavailable message did not get exactly one navigable fallback",
                    )
            telegram.edit_error = "Bad Request: can't parse entities: Unsupported start tag"
            before_bad_edit = len(telegram.calls)
            try:
                await dispatch(callback="cmd:summary")
            except TelegramBadRequest:
                pass
            else:
                raise RuntimeError("Unexpected Telegram edit error was silently swallowed")
            require(
                not any(
                    call.__api_method__ == "sendMessage"
                    for call in telegram.calls[before_bad_edit:]
                ),
                "Unexpected Telegram edit error caused a duplicate send",
            )
            print(
                "PASS: unchanged edits do not duplicate messages; only known missing/noneditable errors fall back"
            )

            chosen = expected["upcoming"][0]
            paid = await control("/pay-first", "POST")
            require(
                paid["id"] == chosen["id"] and paid["status"] == "paid",
                "Fixture did not update the selected occurrence through the API",
            )
            changed_list = await application.api_client.fetch_payments(
                "upcoming", limit=5, offset=0
            )
            require(
                all(item["id"] != chosen["id"] for item in changed_list["items"]),
                "Fixture mutation did not change the list before opening the old card",
            )
            card_calls = await dispatch(callback="card:" + chosen["id"])
            card_messages = [call for call in card_calls if call.__api_method__ == "sendMessage"]
            require(
                len(card_messages) == 1
                and html.escape(chosen["title"], quote=False) in card_messages[0].text,
                "Old card callback opened a different occurrence after the list changed",
            )
            require("Оплач" in card_messages[0].text, "Card did not show the saved paid state")
            missing = await dispatch(callback="card:" + str(UUID(int=1)))
            require(
                any(
                    getattr(call, "text", None) == application.T["PAYMENT_NOT_FOUND"]
                    for call in missing
                ),
                "A missing UUID was not handled as an expired card",
            )
            print(
                "PASS: UUID card reads fresh data after list changes; missing period handled safely"
            )

            before = (len(api_calls), len(other_calls))
            for callback in (
                "card:not-a-uuid",
                "card:1",
                "pg:all:-1",
                "pg:unknown:0",
                "pg:all:bad",
                "cmd:unknown",
                f"card:{chosen['id']}:unknown:0",
                f"card:{chosen['id']}:all:-1",
            ):
                await dispatch(callback=callback)
            require(
                (len(api_calls), len(other_calls)) == before, "Malformed callbacks queried the API"
            )
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
            for command in ("/all", "/summary", "/overdue"):
                await dispatch(command=command, chat=allowed - 1)
            for callback in ("cmd:all", "cmd:summary", "pg:all:1", "card:" + chosen["id"]):
                await dispatch(callback=callback, chat=allowed - 1)
            require(
                (len(api_calls), len(other_calls)) == before,
                "Foreign chat queried lists, cards or summary",
            )
            print("PASS: malformed and foreign-chat callbacks cannot query financial data")

            for callback in (
                "pg:all:0",
                "cmd:summary",
                f"card:{chosen['id']}:all:0",
                "card:" + chosen["id"],
            ):
                await dispatch(callback=callback, inaccessible=True)
                await dispatch(callback=callback, inline=True)
            telegram.answer_error = (
                "Bad Request: query is too old and response timeout expired or query ID is invalid"
            )
            expired = await dispatch(callback="pg:all:0")
            require(
                len(expired) == 1 and telegram.answer_error is None,
                "Expired callback continued rendering after acknowledgement failed",
            )
            require(
                (len(api_calls), len(other_calls)) == before,
                "Inaccessible or expired callbacks queried financial data",
            )
            print(
                "PASS: inaccessible, inline and expired callbacks acknowledge once without financial queries"
            )

            last_paid = await control("/pay-last-upcoming", "POST")
            removed = {chosen["id"], *last_paid["paid_ids"]}
            remaining = [item for item in expected["upcoming"] if item["id"] not in removed]
            require(
                len(remaining) == 49, "Page-shrink fixture did not cross the last-page boundary"
            )
            check_page(
                await dispatch(callback="pg:upcoming:10"),
                remaining[45:50],
                "upcoming",
                9,
                "editMessageText",
            )
            await control("/pay-overdue", "POST")
            empty = output_message(await dispatch(callback="pg:overdue:0"), "editMessageText")
            require(
                not any(value.startswith("card:") for value in callbacks(empty)),
                "Empty overdue view still exposes payment cards",
            )
            require(
                {"pg:overdue:0", "cmd:start"} <= set(callbacks(empty)),
                "Empty overdue view has no refresh or menu",
            )
            require(
                (await application.api_client.fetch_payments("overdue", limit=5))["total"] == 0,
                "Empty-state fixture did not persist through the real API",
            )
            print(
                "PASS: real payment updates clamp a stale last page and produce a navigable empty overdue view"
            )

            for callback in ("pg:all:1", "cmd:summary", f"card:{chosen['id']}:all:0"):
                before_proxy = await control("/proxy-status")
                await control("/fail-next", "POST")
                error_view = output_message(await dispatch(callback=callback), "editMessageText")
                require(
                    application.T["API_UNAVAILABLE"] in error_view.text,
                    "HTTP 503 did not produce the unavailable view",
                )
                require(
                    {callback, "cmd:start"} <= set(callbacks(error_view)),
                    "API error lost its exact retry context or menu",
                )
                failed_proxy = await control("/proxy-status")
                require(
                    failed_proxy["failures"] == before_proxy["failures"] + 1,
                    "The real HTTP failure was not consumed exactly once",
                )
                recovered = output_message(await dispatch(callback=callback), "editMessageText")
                require(
                    application.T["API_UNAVAILABLE"] not in recovered.text,
                    "Retry did not recover through the real API",
                )
                require(
                    (await control("/proxy-status"))["forwarded"] > failed_proxy["forwarded"],
                    "Retry did not reach the real backend",
                )
            print(
                "PASS: local HTTP 503 preserves list/card/summary retry context and recovers through the real API"
            )
            await control("/restore-payments", "POST")
    finally:
        await application.api_client.close()
        await bot.session.close()
    smoke_and_environment()


if __name__ == "__main__":
    asyncio.run(main())
