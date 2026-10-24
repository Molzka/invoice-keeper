"""Full registration/MFA journeys through real HTTP, PostgreSQL and Dispatcher."""

import asyncio
import base64
import hashlib
import hmac
import itertools
import json
import os
import re
import secrets
import struct
import sys
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import aiohttp
import bot as application
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Message, Update

API = "http://backend:8000/api/v1"
FIXTURE = "http://access-fixture:8082"
ORIGIN = "http://access-check.local"
PRIVATE_ID = 741852963


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def totp(secret, instant=None):
    """Client-side authenticator; server verification remains the actual application."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int(time.time() if instant is None else instant) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


class Client:
    def __init__(self, base=API):
        self.base, self.csrf = base, None
        self.session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True), timeout=aiohttp.ClientTimeout(total=30)
        )

    async def close(self):
        await self.session.close()

    async def request(
        self, path, *, method="GET", body=None, expected=200, headers=None, with_status=False
    ):
        request_headers = {"Origin": ORIGIN}
        if self.csrf:
            request_headers["X-CSRF-Token"] = self.csrf
        request_headers.update(headers or {})
        async with self.session.request(
            method, self.base + path, json=body, headers=request_headers, allow_redirects=False
        ) as response:
            statuses = (expected,) if isinstance(expected, int) else expected
            require(
                response.status in statuses,
                f"{method} {path}: HTTP {response.status}, expected {statuses}",
            )
            if self.base == API:
                require(
                    "no-store" in response.headers.get("Cache-Control", ""),
                    "Sensitive API response is cacheable: " + path,
                )
            payload = await response.json() if response.status != 204 else None
            if isinstance(payload, dict) and "csrf_token" in payload:
                self.csrf = payload["csrf_token"]
            return (response.status, payload) if with_status else payload

    async def post(self, path, body=None, **kwargs):
        return await self.request(path, method="POST", body={} if body is None else body, **kwargs)

    async def login(self, username, password, **kwargs):
        return await self.post(
            "/auth/login", {"username": username, "password": password}, **kwargs
        )


class LocalTelegram(BaseSession):
    """Only outgoing bot acknowledgements; backend code delivery uses real local HTTP."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise RuntimeError("External Telegram downloads are forbidden")
        yield b""

    async def make_request(self, bot, method, timeout=None):
        require(method.__api_method__ == "sendMessage", "Unexpected bot transport method")
        require(
            not re.search(r"<code>[0-9]{6}</code>", method.text),
            "The bridge returned a personal code through the bot handler",
        )
        self.calls.append(method)
        return Message(
            message_id=len(self.calls),
            date=datetime.now(UTC),
            chat={
                "id": int(method.chat_id),
                "type": "private" if int(method.chat_id) > 0 else "supergroup",
            },
            text=method.text,
        ).as_(bot)


async def denial_scenarios(client, fixture, admin):
    """Independent account keeps production username/challenge limits meaningful."""
    username, password = "denial_" + secrets.token_hex(6), secrets.token_urlsafe(24)
    member = await admin.post("/users", {"username": username, "password": password}, expected=201)
    user_id = member["id"]
    user, other = client(), client()
    bridge = client("http://backend:8000")
    private_id = PRIVATE_ID + 1
    try:
        await user.login(username, password)
        await user.post("/auth/security/reauth", {"password": password})
        expired_setup = await user.post("/auth/security/totp/setup")
        await fixture.post(
            "/expire",
            {"user_id": user_id, "purpose": "totp_setup", "setup_id": expired_setup["setup_id"]},
        )
        await user.post(
            "/auth/security/totp/confirm",
            {
                "setup_id": expired_setup["setup_id"],
                "code": totp(expired_setup["secret"]),
            },
            expected=409,
        )
        require(
            not (await user.request("/auth/security"))["mfa_enabled"],
            "An expired setup enabled an authenticator",
        )
        await user.post("/auth/security/reauth", {"password": password})
        setup = await user.post("/auth/security/totp/setup")
        enrolled = await user.post(
            "/auth/security/totp/confirm",
            {
                "setup_id": setup["setup_id"],
                "code": totp(setup["secret"]),
            },
        )
        codes = enrolled["recovery_codes"]
        await user.post("/auth/security/reauth", {"password": password}, expected=422)
        await user.post("/auth/security/disable", expected=409)
        require(
            (await user.request("/auth/security"))["mfa_enabled"],
            "Password-only reauthentication disabled an existing factor",
        )

        await other.login(username, password)
        await other.post("/auth/mfa/verify", {"method": "recovery", "code": codes.pop()})

        async def link_setup():
            await user.post(
                "/auth/security/reauth",
                {
                    "password": password,
                    "method": "recovery",
                    "code": codes.pop(),
                },
            )
            link = await user.post("/auth/security/telegram/setup")
            token = parse_qs(urlsplit(link["link"]).query)["start"][0].removeprefix("mfa_")
            claim = {
                "token": token,
                "telegram_id": private_id,
                "chat_id": private_id,
                "username": "denial_fixture",
                "display_name": "Проверка отказов",
            }
            return link, claim

        link, claim = await link_setup()
        await fixture.post(
            "/expire",
            {"user_id": user_id, "purpose": "telegram_setup", "setup_id": link["setup_id"]},
        )
        before = len((await fixture.request("/messages"))["messages"])
        await bridge.post(
            "/internal/v1/telegram-auth/claim",
            claim,
            expected=409,
            headers={"Authorization": "Bearer " + os.environ["BOT_INTERNAL_TOKEN"]},
        )
        require(
            len((await fixture.request("/messages"))["messages"]) == before,
            "An expired private link sent a code",
        )

        link, claim = await link_setup()
        await bridge.post(
            "/internal/v1/telegram-auth/claim",
            claim,
            headers={"Authorization": "Bearer " + os.environ["BOT_INTERNAL_TOKEN"]},
        )
        messages = (await fixture.request("/messages"))["messages"]
        personal = [item for item in messages if item["chat"]["id"] == private_id]
        require(len(personal) == 1, "Private claim did not deliver exactly one code")
        code = re.search(r"<code>([0-9]{6})</code>", personal[0]["text"])[1]
        confirmation = {"setup_id": link["setup_id"], "code": code}
        await other.post("/auth/security/telegram/confirm", confirmation, expected=409)
        require(
            (await other.request("/auth/me"))["user"]["id"] == user_id,
            "Cross-session confirmation check did not use an authenticated browser",
        )
        await fixture.post(
            "/expire",
            {
                "user_id": user_id,
                "purpose": "telegram_setup",
                "setup_id": link["setup_id"],
                "code_only": True,
            },
        )
        await user.post("/auth/security/telegram/confirm", confirmation, expected=422)
        await fixture.post(
            "/expire",
            {"user_id": user_id, "purpose": "telegram_setup", "setup_id": link["setup_id"]},
        )
        await user.post("/auth/security/telegram/confirm", confirmation, expected=409)
        require(
            (await user.request("/auth/security"))["methods"] == ["totp"],
            "Cross-session or expired confirmation linked Telegram",
        )
        print(
            "PASS: expired TOTP/link/code, browser-bound confirmation and strong reauthentication"
        )

        expired_login = client()
        await expired_login.login(username, password)
        pending_token = next(
            item.value for item in expired_login.session.cookie_jar if item.key == "mfa_pending"
        )
        await fixture.post(
            "/expire",
            {
                "user_id": user_id,
                "purpose": "login",
                "token_hash": hashlib.sha256(pending_token.encode()).hexdigest(),
            },
        )
        await expired_login.post(
            "/auth/mfa/verify", {"method": "recovery", "code": codes[-1]}, expected=401
        )
        await expired_login.request("/auth/me", expected=401)
        locked = client()
        await locked.login(username, password)
        for _ in range(5):
            rejected = await locked.post(
                "/auth/mfa/verify",
                {
                    "method": "recovery",
                    "code": "invalid-recovery-proof",
                },
                expected=422,
            )
            require(
                rejected["error"]["code"] == "MFA_CODE_INVALID", "Wrong attempt rejected elsewhere"
            )
        refused = await locked.post(
            "/auth/mfa/verify", {"method": "recovery", "code": codes[-1]}, expected=401
        )
        require(
            refused["error"]["code"] == "MFA_CHALLENGE_EXPIRED",
            "The sixth proof was not rejected by challenge exhaustion",
        )
        await locked.request("/auth/me", expected=401)

        pending = client()
        await pending.login(username, password)
        correct_csrf = pending.csrf
        for supplied in (None, admin.csrf):
            pending.csrf = supplied
            for path, body in (
                ("/auth/mfa/verify", {"method": "recovery", "code": codes[-1]}),
                ("/auth/mfa/telegram/send", {}),
                ("/auth/mfa/cancel", {}),
            ):
                denied = await pending.post(path, body, expected=403)
                require(
                    denied["error"]["code"] == "CSRF_FAILED",
                    "Pre-MFA operation did not enforce its own CSRF token",
                )
        pending.csrf = correct_csrf
        await pending.request("/auth/me", expected=401)
        print("PASS: expired login, five wrong proofs and missing/foreign pre-MFA CSRF")

        replacement = secrets.token_urlsafe(24)
        await admin.request("/users/" + user_id, method="PATCH", body={"password": replacement})
        await user.request("/auth/me", expected=401)
        await pending.post(
            "/auth/mfa/verify", {"method": "recovery", "code": codes[-1]}, expected=401
        )
        reset = client()
        await reset.login(username, password, expected=401)
        required = await reset.login(username, replacement)
        require(
            required["mfa_required"] and "totp" in required["methods"],
            "An administrator password reset bypassed an existing second factor",
        )
        await reset.request("/auth/me", expected=401)
        await reset.post("/auth/mfa/verify", {"method": "recovery", "code": codes.pop()})
        require(
            (await reset.request("/auth/security"))["methods"] == ["totp"],
            "Password reset removed the enrolled authenticator",
        )
        print("PASS: administrator password reset revokes old access while preserving MFA")
    finally:
        await admin.request("/users/" + user_id, method="DELETE", expected=204)


async def initial():
    clients = []

    def client(base=API):
        value = Client(base)
        clients.append(value)
        return value

    fixture, admin, guest, user, other_session = (
        client(FIXTURE),
        client(),
        client(),
        client(),
        client(),
    )
    telegram = LocalTelegram()
    bot = Bot(os.environ["BOT_TOKEN"], session=telegram)
    dispatcher = Dispatcher()
    dispatcher.include_router(application.secure)
    dispatcher.include_router(application.public)
    sequence = itertools.count(1)

    async def dispatch(
        argument, *, chat=PRIVATE_ID, chat_type="private", user_id=PRIVATE_ID, is_bot=False
    ):
        before = len(telegram.calls)
        await dispatcher.feed_update(
            bot,
            Update.model_validate(
                {
                    "update_id": next(sequence),
                    "message": {
                        "message_id": next(sequence),
                        "date": int(time.time()),
                        "chat": {"id": chat, "type": chat_type},
                        "from": {
                            "id": user_id,
                            "is_bot": is_bot,
                            "first_name": "Проверка <&>",
                            "username": "access_fixture",
                        },
                        "text": "/start " + argument,
                        "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
                    },
                }
            ),
        )
        require(len(telegram.calls) == before + 1, "Link command did not render one safe reply")
        return telegram.calls[-1].text

    async def captcha():
        challenge = await guest.request("/registration/challenge")
        return (await fixture.post("/solve", challenge))["altcha"]

    async def latest_code():
        messages = (await fixture.request("/messages"))["messages"]
        require(
            messages and all(item["chat"]["id"] == PRIVATE_ID for item in messages),
            "Personal codes escaped the confirmed private chat",
        )
        return re.search(r"<code>([0-9]{6})</code>", messages[-1]["text"])[1]

    password = secrets.token_urlsafe(24)
    username = "access_" + secrets.token_hex(6)
    try:
        await admin.login(os.environ["ADMIN_USERNAME"], os.environ["ADMIN_PASSWORD"])
        await guest.request("/registration/requests", expected=401)
        await guest.post(
            "/registration/requests",
            {
                "username": username,
                "password": password,
                "password_confirm": password,
                "message": "Проверка доступа <&>",
                "altcha": "invalid",
            },
            expected=422,
        )
        payload = {
            "username": username,
            "password": password,
            "password_confirm": password,
            "message": "Проверка доступа <&>",
            "altcha": await captcha(),
        }
        malformed = base64.b64encode(
            json.dumps(
                {
                    "challenge": {"parameters": {"data": {"id": 1}}},
                    "solution": {},
                }
            ).encode()
        ).decode()
        await guest.post("/registration/requests", {**payload, "altcha": malformed}, expected=422)
        accepted = await guest.post("/registration/requests", payload, expected=202)
        require(accepted["status"] == "pending", "Registration granted immediate access")
        await guest.request("/auth/me", expected=401)
        await guest.login(username, password, expected=401)
        await guest.post("/registration/requests", payload, expected=422)
        payload["altcha"] = await captcha()
        duplicate = await guest.post("/registration/requests", payload, expected=202)
        require(duplicate == accepted, "Duplicate registration exposes account existence")
        requests = await admin.request("/registration/requests?status=pending&limit=100&offset=0")
        own = [item for item in requests["items"] if item["username"] == username]
        require(
            len(own) == 1 and "password_hash" not in own[0],
            "Registration duplicated or exposed a password hash",
        )
        request_id = own[0]["id"]
        results = await asyncio.gather(
            *[
                admin.post(
                    f"/registration/requests/{request_id}/approve",
                    expected=(200, 409),
                    with_status=True,
                )
                for _ in range(2)
            ]
        )
        require(any(status == 200 for status, _ in results), "Neither approval succeeded")
        users = await admin.request("/users?limit=100&offset=0")
        members = [item for item in users["items"] if item["username"] == username]
        require(
            len(members) == 1 and members[0]["role"] == "user",
            "Concurrent approval did not create exactly one ordinary user",
        )
        user_id = members[0]["id"]
        await user.login(username, password)
        await other_session.login(username, password)
        await user.request("/registration/requests", expected=403)
        await user.post(f"/registration/requests/{request_id}/approve", expected=403)
        await user.post("/users", {"username": "cannot_create", "password": password}, expected=403)
        denied = await admin.post(
            "/auth/security/reauth",
            {
                "password": os.environ["ADMIN_PASSWORD"],
            },
            expected=403,
        )
        require(
            denied["error"]["code"] == "ADMIN_ACCOUNT_PROTECTED",
            "Administrator security settings lost protection",
        )
        security = await user.request("/auth/security")
        require(
            not security["mfa_enabled"]
            and {"totp", "telegram"} <= set(security["available_methods"]),
            "Optional MFA or configured factors are unavailable",
        )
        print("PASS: local ALTCHA, pending access, duplicate/racing approval and role protection")

        await user.post("/auth/security/totp/setup", expected=(401, 403, 409))
        await user.post("/auth/security/reauth", {"password": password})
        setup = await user.post("/auth/security/totp/setup")
        await user.post("/auth/security/totp/setup", expected=(401, 403, 409))
        require(setup["secret"] in setup["otpauth_uri"], "TOTP URI lost its local secret")
        current_code = totp(setup["secret"])
        await user.post(
            "/auth/security/totp/confirm",
            {
                "setup_id": setup["setup_id"],
                "code": "000000" if current_code != "000000" else "111111",
            },
            expected=422,
        )
        enrolled = await user.post(
            "/auth/security/totp/confirm",
            {
                "setup_id": setup["setup_id"],
                "code": current_code,
            },
        )
        codes = enrolled["recovery_codes"]
        require(
            len(codes) == len(set(codes)) == 10 and enrolled["security"]["mfa_enabled"],
            "TOTP confirmation did not issue ten independent recovery codes",
        )
        await other_session.request("/auth/me", expected=401)
        pending = client()
        challenge = await pending.login(username, password)
        require(
            challenge["mfa_required"] and "recovery" in challenge["methods"],
            "Password-only login bypassed MFA",
        )
        await pending.request("/auth/me", expected=401)
        await pending.request("/payment-occurrences", expected=401)
        await pending.post(
            "/auth/mfa/verify", {"method": "totp", "code": current_code}, expected=422
        )
        used_code = codes.pop()
        verified = await pending.post("/auth/mfa/verify", {"method": "recovery", "code": used_code})
        require(verified["user"]["id"] == user_id, "Recovery authenticated a different user")
        await pending.post(
            "/auth/mfa/verify", {"method": "recovery", "code": used_code}, expected=(401, 403)
        )
        replay = client()
        await replay.login(username, password)
        await replay.post(
            "/auth/mfa/verify", {"method": "recovery", "code": used_code}, expected=422
        )
        await replay.post("/auth/mfa/cancel", expected=204)
        await replay.post(
            "/auth/mfa/verify", {"method": "recovery", "code": codes[-1]}, expected=(401, 403)
        )
        print("PASS: TOTP enrollment, pre-MFA denial, single-use recovery and cancellation")

        # A real time-step transition, without overriding application time.
        delay = 30 - time.time() % 30 + 1
        print(f"Waiting {int(delay)}s for the next authenticator time step", flush=True)
        await asyncio.sleep(delay)
        totp_login = client()
        await totp_login.login(username, password)
        await totp_login.post("/auth/mfa/verify", {"method": "totp", "code": totp(setup["secret"])})
        await totp_login.request("/auth/me")

        await user.post(
            "/auth/security/reauth",
            {"password": password, "method": "recovery", "code": codes.pop()},
        )
        link = await user.post("/auth/security/telegram/setup")
        argument = parse_qs(urlsplit(link["link"]).query)["start"][0]
        require(re.fullmatch(r"mfa_[A-Za-z0-9_-]{43}", argument), "Invalid private deep link")
        token = argument.removeprefix("mfa_")
        initial_messages = len((await fixture.request("/messages"))["messages"])
        for chat_type in ("group", "supergroup", "channel"):
            await dispatch(argument, chat=int(os.environ["CHAT_ID"]), chat_type=chat_type)
        await dispatch(argument, user_id=PRIVATE_ID + 1)
        await dispatch(argument, is_bot=True)
        await dispatch("mfa_invalid")
        waiting = await user.request("/auth/security/telegram/setup/" + link["setup_id"])
        require(waiting["status"] == "waiting", "A non-private update claimed the link")
        require(
            len((await fixture.request("/messages"))["messages"]) == initial_messages,
            "An invalid link or non-private update sent a code",
        )
        await totp_login.request(
            "/auth/security/telegram/setup/" + link["setup_id"], expected=(403, 404, 409)
        )
        bridge = client("http://backend:8000")
        claim = {
            "token": token,
            "telegram_id": PRIVATE_ID,
            "chat_id": PRIVATE_ID,
            "username": "access_fixture",
            "display_name": "Проверка <&>",
        }
        await bridge.post("/internal/v1/telegram-auth/claim", claim, expected=(401, 403))
        await bridge.post(
            "/internal/v1/telegram-auth/claim",
            claim,
            expected=(401, 403),
            headers={"Authorization": "Bearer wrong-service-token"},
        )
        await bridge.post(
            "/internal/v1/telegram-auth/claim",
            {**claim, "chat_id": -1},
            expected=422,
            headers={"Authorization": "Bearer " + os.environ["BOT_INTERNAL_TOKEN"]},
        )
        reply = await dispatch(argument)
        require(reply == application.T["MFA_LINK_CLAIMED"], "Private link was not accepted")
        claimed = await user.request("/auth/security/telegram/setup/" + link["setup_id"])
        require(
            claimed["status"] == "claimed" and claimed["account"]["id"] == str(PRIVATE_ID),
            "Private update identity was not bound to the browser setup",
        )
        messages_after_claim = len((await fixture.request("/messages"))["messages"])
        await dispatch(argument)
        require(
            len((await fixture.request("/messages"))["messages"]) == messages_after_claim,
            "An already claimed link sent a second code",
        )
        linked = await user.post(
            "/auth/security/telegram/confirm",
            {
                "setup_id": link["setup_id"],
                "code": await latest_code(),
            },
        )
        require(
            set(linked["security"]["methods"]) == {"totp", "telegram"},
            "Telegram setup replaced the existing authenticator",
        )
        print(
            "PASS: private Dispatcher linking, identity guards, bearer boundary and replay denial"
        )

        telegram_login = client()
        await telegram_login.login(username, password)
        await telegram_login.request("/auth/me", expected=401)
        await telegram_login.post("/auth/mfa/telegram/send")
        await telegram_login.post("/auth/mfa/telegram/send", expected=429)
        await telegram_login.post(
            "/auth/mfa/verify", {"method": "telegram", "code": await latest_code()}
        )
        await telegram_login.request("/auth/me")
        failed_delivery = client()
        await failed_delivery.login(username, password)
        await fixture.post("/fail-next")
        await failed_delivery.post("/auth/mfa/telegram/send", expected=503)
        await failed_delivery.request("/auth/me", expected=401)
        await failed_delivery.post("/auth/mfa/verify", {"method": "recovery", "code": codes.pop()})
        print("PASS: real local Telegram HTTP, resend limit and delivery-failure recovery")

        # Rotate the recovery set through an actual strong reauthentication.
        await user.post(
            "/auth/security/reauth",
            {"password": password, "method": "recovery", "code": codes.pop()},
        )
        renewed = await user.post("/auth/security/recovery/regenerate")
        require(
            len(renewed["recovery_codes"]) == 10,
            "Recovery regeneration did not create a complete replacement set",
        )
        old_recovery = client()
        await old_recovery.login(username, password)
        await old_recovery.post(
            "/auth/mfa/verify", {"method": "recovery", "code": codes[-1]}, expected=422
        )
        await fixture.post(
            "/state",
            {
                "username": username,
                "password": password,
                "user_id": user_id,
                "secret": setup["secret"],
                "codes": renewed["recovery_codes"],
                "pending_cookies": {
                    item.key: item.value for item in old_recovery.session.cookie_jar
                },
                "pending_csrf": old_recovery.csrf,
            },
        )
        print("PASS: recovery regeneration invalidates the old set; state ready for API restart")
        await denial_scenarios(client, fixture, admin)
    finally:
        await bot.session.close()
        await application.api_client.close()
        await asyncio.gather(*(value.close() for value in clients))


async def after_restart():
    fixture, user, pending, admin = Client(FIXTURE), Client(), Client(), Client()
    try:
        state = await fixture.request("/state")
        challenge = await user.login(state["username"], state["password"])
        require(
            challenge["mfa_required"]
            and set(challenge["methods"]) == {"totp", "telegram", "recovery"},
            "API recreation lost an enrolled factor",
        )
        await user.request("/auth/me", expected=401)
        proof = {"method": "recovery", "code": state["codes"].pop()}
        outcomes = await asyncio.gather(
            *[
                user.post(
                    "/auth/mfa/verify", proof, expected=(200, 401, 403, 422), with_status=True
                )
                for _ in range(2)
            ]
        )
        require(
            sum(status == 200 for status, _ in outcomes) == 1,
            "Concurrent verification consumed one recovery code more than once",
        )
        security = await user.request("/auth/security")
        require(
            security["telegram"]["id"] == str(PRIVATE_ID), "API recreation lost private identity"
        )
        pending.session.cookie_jar.update_cookies(state["pending_cookies"])
        pending.csrf = state["pending_csrf"]
        await admin.login(os.environ["ADMIN_USERNAME"], os.environ["ADMIN_PASSWORD"])
        await admin.request("/users/" + state["user_id"], method="DELETE", expected=204)
        await user.request("/auth/me", expected=401)
        await pending.post(
            "/auth/mfa/verify",
            {"method": "recovery", "code": state["codes"].pop()},
            expected=(401, 403),
        )
        print(
            "PASS: restart preserves MFA and recovery; deleting a user revokes sessions/challenges"
        )
    finally:
        await asyncio.gather(fixture.close(), user.close(), pending.close(), admin.close())


if __name__ == "__main__":
    asyncio.run(initial() if sys.argv[1] == "initial" else after_restart())
