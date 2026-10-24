"""Internal-only fixture service for the disposable bot/API integration stack."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import UUID
from zoneinfo import ZoneInfo

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, web
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

    auth = request(
        "POST",
        "/auth/login",
        {
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
    )
    csrf = auth["csrf_token"]
    user = request(
        "POST",
        "/users",
        {
            "username": os.environ["API_USERNAME"],
            "password": os.environ["API_PASSWORD"],
        },
        201,
    )
    today = datetime.now(ZoneInfo(auth["timezone"])).date()

    def payment(title, due, *, paid=False, stopped=False, amount="123.45", currency="RUB"):
        created = request(
            "POST",
            "/recurring-payments",
            {
                "title": title,
                "amount": amount,
                "currency": currency,
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
        title = f"Bot upcoming {index:02d} <&>"
        if index == 0:
            title = (title + " 🧾Кириллица<&>" * 20)[:200]
        payment(
            title,
            today + timedelta(days=index % 7),
            currency=("RUB", "USD", "EUR")[index % 3],
        )
    payment("Bot day seven excluded", today + timedelta(days=7))
    payment("Bot paid excluded", today, paid=True, amount="7.89", currency="USD")
    for index in range(3):
        payment(f"Bot overdue {index}", today - timedelta(days=index + 1), stopped=index == 2)
    payment("Bot overdue paid excluded", today - timedelta(days=1), paid=True, currency="EUR")
    expected = {"timezone": auth["timezone"], "today": today.isoformat()}
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
    all_page = request("GET", "/payment-occurrences?limit=100&offset=0")
    if all_page["total"] > 100:
        raise RuntimeError("Fixture all-list unexpectedly needs more than one API page")
    expected["all"] = all_page["items"]
    expected["summary"] = request("GET", "/payments/summary")
    return UUID(user["id"]), expected, request


async def application():
    database = Database(settings.database_url)
    async with database.session_factory() as session:
        name = await session.scalar(text("SELECT current_database()"))
        if not name.startswith("bot_") or not name.endswith("_test"):
            raise RuntimeError("Refusing to use a non-fixture database")
    user_id, expected, api_request = seed()
    changed_periods = set()
    proxy_client = ClientSession(cookie_jar=DummyCookieJar(), timeout=ClientTimeout(total=15))
    proxy_state = {"fail_next": False, "failures": 0, "forwarded": 0}

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

    async def pay_first(_request):
        item = await asyncio.to_thread(
            api_request,
            "PATCH",
            "/payment-occurrences/" + expected["upcoming"][0]["id"],
            {"status": "paid", "paid_on": expected["today"]},
        )
        changed_periods.add(item["id"])
        return web.json_response(item)

    async def pay_periods(items):
        for item in items:
            await asyncio.to_thread(
                api_request,
                "PATCH",
                "/payment-occurrences/" + item["id"],
                {"status": "paid", "paid_on": expected["today"]},
            )
            changed_periods.add(item["id"])

    async def pay_last_upcoming(_request):
        await pay_periods(expected["upcoming"][-2:])
        return web.json_response({"paid_ids": [item["id"] for item in expected["upcoming"][-2:]]})

    async def pay_overdue(_request):
        await pay_periods(expected["overdue"])
        return web.json_response({"paid_count": len(expected["overdue"])})

    async def restore_payments(_request):
        for identifier in sorted(changed_periods):
            await asyncio.to_thread(
                api_request,
                "PATCH",
                "/payment-occurrences/" + identifier,
                {"status": "unpaid", "paid_on": None},
            )
        changed_periods.clear()
        return web.json_response({"restored": True})

    async def fail_next(_request):
        proxy_state["fail_next"] = True
        return web.json_response(proxy_state)

    async def proxy_status(_request):
        return web.json_response(proxy_state)

    async def proxy(request):
        # Keep the real backend's authentication, cookies, payloads and PostgreSQL.
        # Only one requested GET can be replaced with a deliberate HTTP 503.
        if proxy_state["fail_next"] and request.method == "GET":
            proxy_state["fail_next"] = False
            proxy_state["failures"] += 1
            return web.json_response(
                {"error": {"code": "FIXTURE_UNAVAILABLE", "message": "Fixture outage"}},
                status=503,
                headers={"Cache-Control": "no-store"},
            )
        target = os.environ["API_BASE_URL"] + request.raw_path.removeprefix("/api/v1")
        headers = {
            key: request.headers[key]
            for key in ("Accept", "Content-Type", "Cookie", "Origin", "X-CSRF-Token")
            if key in request.headers
        }
        async with proxy_client.request(
            request.method,
            target,
            headers=headers,
            data=await request.read(),
            allow_redirects=False,
        ) as response:
            body = await response.read()
            proxy_state["forwarded"] += 1
            headers = [
                (key, value)
                for key, value in response.headers.items()
                if key.lower() in {"content-type", "set-cookie", "cache-control", "retry-after"}
            ]
            return web.Response(status=response.status, body=body, headers=headers)

    async def close(_app):
        await proxy_client.close()
        await database.dispose()

    app = web.Application()
    app.add_routes(
        [
            web.get("/fixtures", fixtures),
            web.get("/sessions", sessions),
            web.post("/expire", expire),
            web.post("/pay-first", pay_first),
            web.post("/pay-last-upcoming", pay_last_upcoming),
            web.post("/pay-overdue", pay_overdue),
            web.post("/restore-payments", restore_payments),
            web.post("/fail-next", fail_next),
            web.get("/proxy-status", proxy_status),
            web.route("*", "/api/v1/{path:.*}", proxy),
        ]
    )
    app.on_cleanup.append(close)
    return app


if __name__ == "__main__":
    web.run_app(application(), host="0.0.0.0", port=8082, access_log=None)
