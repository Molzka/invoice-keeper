"""Disposable Telegram transport and ALTCHA client helper; no production credentials."""

import asyncio
import os
import re
import time
from uuid import UUID

import altcha
from aiohttp import web
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def application():
    messages = []
    state = {}
    failure = False
    token = os.environ["BOT_TOKEN"]
    if token != "123456789:" + "A" * 35:
        raise RuntimeError("Fixture requires the fixed fake Telegram token")
    database_url = os.environ["DATABASE_URL"]
    database = make_url(database_url)
    if (
        database.host != "postgres"
        or not database.database
        or not re.fullmatch(r"access_[0-9a-f]{12}_test", database.database)
    ):
        raise RuntimeError("Fixture expiry requires its own disposable database")
    engine = create_async_engine(database_url)

    async def health(_request):
        return web.json_response({"ok": True})

    async def send(request):
        nonlocal failure
        if request.match_info["token"] != token:
            raise web.HTTPUnauthorized()
        body = await request.post()
        chat = int(body["chat_id"])
        if chat <= 0 or not re.search(r"<code>[0-9]{6}</code>", body["text"]):
            raise RuntimeError("Personal code escaped its private-chat boundary")
        if body.get("protect_content") != "true":
            raise RuntimeError("Personal code forwarding protection is missing")
        if failure:
            failure = False
            return web.json_response(
                {"ok": False, "error_code": 503, "description": "Local fixture unavailable"},
                status=503,
            )
        message = {
            "message_id": len(messages) + 1,
            "date": int(time.time()),
            "chat": {"id": chat, "type": "private"},
            "text": body["text"],
        }
        messages.append(message)
        return web.json_response({"ok": True, "result": message})

    async def captured(_request):
        return web.json_response({"messages": messages})

    async def fail(_request):
        nonlocal failure
        failure = True
        return web.json_response({"armed": True})

    async def saved(request):
        if request.method == "POST":
            state.clear()
            state.update(await request.json())
        return web.json_response(state)

    async def solve(request):
        challenge = altcha.Challenge.from_dict(await request.json())
        solution = await asyncio.to_thread(altcha.solve_challenge, challenge)
        return web.json_response({"altcha": altcha.Payload(challenge, solution).to_base64()})

    async def expire(request):
        # Arrange elapsed time in an owned PostgreSQL row; real HTTP still performs
        # every verification/claim/confirmation and decides whether it is valid.
        body = await request.json()
        user_id = UUID(body["user_id"])
        purpose = body["purpose"]
        if purpose not in {"login", "totp_setup", "telegram_setup"}:
            raise web.HTTPBadRequest()
        if "setup_id" in body:
            selector, value = "id", UUID(body["setup_id"])
        else:
            selector, value = "token_hash", body["token_hash"]
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise web.HTTPBadRequest()
        field = "code_expires_at" if body.get("code_only") is True else "expires_at"
        async with engine.begin() as connection:
            actual = await connection.scalar(text("SELECT current_database()"))
            if actual != database.database:
                raise RuntimeError("Fixture connected to an unexpected database")
            changed = await connection.execute(
                text(
                    f"UPDATE mfa_challenges SET {field} = now() - interval '1 second' "
                    f"WHERE user_id = :user_id AND purpose = :purpose AND {selector} = :value "
                    "AND EXISTS (SELECT 1 FROM users WHERE users.id = mfa_challenges.user_id "
                    "AND users.username LIKE 'denial\\_%' ESCAPE '\\')"
                ),
                {"user_id": user_id, "purpose": purpose, "value": value},
            )
            if changed.rowcount != 1:
                raise RuntimeError("Expiry must target exactly one owned challenge")
        return web.json_response({"expired": 1})

    async def close(_app):
        await engine.dispose()

    app = web.Application(client_max_size=32768)
    app.add_routes(
        [
            web.get("/health", health),
            web.post("/bot{token}/sendMessage", send),
            web.get("/messages", captured),
            web.post("/fail-next", fail),
            web.get("/state", saved),
            web.post("/state", saved),
            web.post("/solve", solve),
            web.post("/expire", expire),
        ]
    )
    app.on_cleanup.append(close)
    return app


if __name__ == "__main__":
    web.run_app(application(), host="0.0.0.0", port=8082, access_log=None)
