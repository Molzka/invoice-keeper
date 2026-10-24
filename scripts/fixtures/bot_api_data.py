"""Internal-only fixture service for the disposable bot/API integration stack."""

import json
import os
from datetime import UTC, datetime, timedelta
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import UUID
from zoneinfo import ZoneInfo

from aiohttp import web
from app.core.config import settings
from app.db.session import Database
from app.models import UserSession
from sqlalchemy import select, text, update


def seed():
    client = build_opener(HTTPCookieProcessor(CookieJar()))
    csrf = None

    def request(method, path, body=None, status=200):
        headers = {"Origin": os.environ["API_ORIGIN"], "Content-Type": "application/json"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        target = os.environ["API_BASE_URL"] + path
        data = None if body is None else json.dumps(body).encode()
        with client.open(Request(target, data, headers, method=method), timeout=10) as response:
            if response.status != status:
                raise RuntimeError("Unexpected API status while creating fixture data")
            payload = response.read()
            return json.loads(payload) if payload else None

    csrf = request(
        "POST",
        "/auth/login",
        {
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
    )["csrf_token"]
    user = request(
        "POST",
        "/users",
        {
            "username": os.environ["API_USERNAME"],
            "password": os.environ["API_PASSWORD"],
        },
        201,
    )
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()

    def payment(title, due, *, paid=False, stopped=False):
        created = request(
            "POST",
            "/recurring-payments",
            {
                "title": title,
                "amount": "123.45",
                "currency": "RUB",
                "first_due_date": due.isoformat(),
                "periodicity": "monthly",
            },
            201,
        )
        if paid:
            periods = request(
                "GET",
                "/payment-occurrences?"
                + urlencode(
                    {
                        "recurring_payment_id": created["id"],
                        "date_from": due,
                        "date_to": due,
                    }
                ),
            )
            request(
                "PATCH",
                "/payment-occurrences/" + periods["items"][0]["id"],
                {"status": "paid", "paid_on": today.isoformat()},
            )
        if stopped:
            request("DELETE", "/recurring-payments/" + created["id"], status=204)

    for index in range(52):
        payment(f"Bot upcoming {index:02d} <&>", today + timedelta(days=index % 7))
    payment("Bot day seven excluded", today + timedelta(days=7))
    payment("Bot paid excluded", today, paid=True)
    for index in range(3):
        payment(f"Bot overdue {index}", today - timedelta(days=index + 1), stopped=index == 2)
    payment("Bot overdue paid excluded", today - timedelta(days=1), paid=True)
    expected = {}
    for kind, filters in {
        "upcoming": {"date_from": today, "date_to": today + timedelta(days=6)},
        "overdue": {"is_overdue": "true"},
    }.items():
        page = request(
            "GET",
            "/payment-occurrences?"
            + urlencode(
                {
                    **filters,
                    "status": "unpaid",
                    "limit": 100,
                    "offset": 0,
                }
            ),
        )
        if page["total"] != (52 if kind == "upcoming" else 3):
            raise RuntimeError("Fixture dates or API payment filters changed")
        expected[kind] = page["items"]
    return UUID(user["id"]), expected


async def application():
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        name = await session.scalar(text("SELECT current_database()"))
        if not name.startswith("bot_") or not name.endswith("_test"):
            raise RuntimeError("Refusing to use a non-fixture database")
    user_id, expected = seed()

    async def fixtures(_request):
        return web.json_response(expected)

    async def sessions(_request):
        async with database.session_factory() as session:
            ids = list(
                await session.scalars(
                    select(UserSession.id)
                    .where(
                        UserSession.user_id == user_id,
                        UserSession.expires_at > datetime.now(UTC),
                    )
                    .order_by(UserSession.id)
                )
            )
        return web.json_response([str(value) for value in ids])

    async def expire(_request):
        async with database.session_factory() as session, session.begin():
            await session.execute(
                update(UserSession)
                .where(UserSession.user_id == user_id)
                .values(
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        return web.json_response({"expired": True})

    async def close(_app):
        await database.dispose()

    app = web.Application()
    app.add_routes(
        [
            web.get("/fixtures", fixtures),
            web.get("/sessions", sessions),
            web.post("/expire", expire),
        ]
    )
    app.on_cleanup.append(close)
    return app


if __name__ == "__main__":
    web.run_app(application(), host="0.0.0.0", port=8082, access_log=None)
