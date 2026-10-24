"""API/PostgreSQL assertions for the disposable Compose integration check."""

import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.session import Database
from app.delivery.schema import deliveries
from app.models import PaymentOccurrence
from sqlalchemy import delete, select, text


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class API:
    def __init__(self):
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = self.request(
            "POST",
            "/auth/login",
            {
                "username": os.environ["ADMIN_USERNAME"],
                "password": os.environ["ADMIN_PASSWORD"],
            },
        )["csrf_token"]

    def request(self, method, path, body=None, status=200):
        headers = {
            "Origin": "http://127.0.0.1:8000",
            "Content-Type": "application/json",
        }
        if hasattr(self, "csrf"):
            headers["X-CSRF-Token"] = self.csrf
        request = Request(
            "http://127.0.0.1:8000/api/v1" + path,
            None if body is None else json.dumps(body).encode(),
            headers,
            method=method,
        )
        with self.client.open(request, timeout=10) as response:
            require(response.status == status, f"Unexpected response for {method} {path}")
            data = response.read()
            return json.loads(data) if data else None

    def create(self, title, date):
        return self.request(
            "POST",
            "/recurring-payments",
            {
                "title": title,
                "amount": "123.45",
                "currency": "RUB",
                "first_due_date": date.isoformat(),
                "periodicity": "monthly",
            },
            201,
        )["id"]


async def occurrences(database, payment):
    async with database.session_factory() as session:
        return list(
            await session.scalars(
                select(PaymentOccurrence)
                .where(
                    PaymentOccurrence.recurring_payment_id == UUID(payment),
                )
                .order_by(PaymentOccurrence.due_date)
            )
        )


async def erase_period(database, payment, date):
    # Intentionally simulate a missed scheduler period, only for API-created fixture IDs.
    async with database.session_factory() as session, session.begin():
        occurrence = await session.scalar(
            select(PaymentOccurrence).where(
                PaymentOccurrence.recurring_payment_id == UUID(payment),
                PaymentOccurrence.due_date == date,
            )
        )
        require(occurrence is not None, "API did not create the fixture period")
        await session.execute(delete(deliveries).where(deliveries.c.occurrence_id == occurrence.id))
        await session.delete(occurrence)


async def inspect(database, payments):
    async with database.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(deliveries)
                    .where(
                        deliveries.c.payment_id.in_([UUID(payment) for payment in payments]),
                    )
                    .order_by(deliveries.c.payment_id, deliveries.c.occurrence_id)
                )
            )
            .mappings()
            .all()
        )
        return [
            {
                key: row[key]
                for key in (
                    "id",
                    "payment_id",
                    "occurrence_id",
                    "status",
                    "attempt_count",
                    "telegram_message_id",
                    "sent_at",
                )
            }
            for row in rows
        ]


async def run(mode, state):
    database = Database(settings.database_url)
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    try:
        async with database.session_factory() as session:
            db_name = await session.scalar(text("SELECT current_database()"))
            require(
                db_name.startswith("worker_") and db_name.endswith("_test"),
                "Refusing to touch a non-fixture database",
            )
        if mode == "prepare-future":
            due = today + timedelta(days=10)
            payment = API().create("Worker future fixture", due)
            await erase_period(database, payment, due)
            return {"future": payment, "due": due.isoformat()}
        if mode == "erase-future":
            await erase_period(database, state["future"], date.fromisoformat(state["due"]))
            return {"removed": True}
        if mode == "verify-future":
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                periods = await occurrences(database, state["future"])
                rows = await inspect(database, [state["future"]])
                if any(item.due_date.isoformat() == state["due"] for item in periods) and rows:
                    require(
                        all(
                            row["status"] == "pending" and row["attempt_count"] == 0 for row in rows
                        ),
                        "A future reminder must not be attempted",
                    )
                    return {"restored": True}
                await asyncio.sleep(0.5)
            raise RuntimeError("Native worker did not restore the missing future period")
        if mode == "prepare-dispatch":
            api = API()
            payments = {
                name: api.create("Worker " + name + " fixture", today)
                for name in ("due", "recovered", "paid", "stopped")
            }
            paid = next(
                item
                for item in await occurrences(database, payments["paid"])
                if item.due_date == today
            )
            api.request(
                "PATCH",
                f"/payment-occurrences/{paid.id}",
                {"status": "paid", "paid_on": today.isoformat()},
            )
            api.request("DELETE", "/recurring-payments/" + payments["stopped"], status=204)
            await erase_period(database, payments["recovered"], today)
            return payments
        require(mode == "verify-dispatch", "Unknown probe mode")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            rows = await inspect(database, state.values())
            sent = [row for row in rows if row["status"] == "sent"]
            if len(sent) >= 2:
                break
            await asyncio.sleep(0.5)
        require(len(sent) == 2, "Expected exactly two confirmed reminders")
        require(
            {str(row["payment_id"]) for row in sent} == {state["due"], state["recovered"]},
            "Paid or stopped payment was sent",
        )
        require(
            all(
                row["attempt_count"] == 1 and row["telegram_message_id"] and row["sent_at"]
                for row in sent
            ),
            "Missing single-attempt durable confirmation",
        )
        require(
            all(
                row["attempt_count"] == 0
                for row in rows
                if str(row["payment_id"]) in (state["paid"], state["stopped"])
            ),
            "Paid or stopped payment was attempted",
        )
        with urlopen("http://telegram-stub:8081/requests", timeout=5) as response:
            requests = json.load(response)
        require(len(requests) == 2, "Unexpected or duplicate Telegram HTTP requests")
        require(
            {row["telegram_message_id"] for row in sent} == {1, 2},
            "Persisted message IDs differ from the HTTP acknowledgements",
        )
        for title in ("due", "recovered"):
            matches = [
                item
                for item in requests
                if "Worker " + title + " fixture" in item["fields"].get("text", [""])[0]
            ]
            require(
                len(matches) == 1 and matches[0]["method"] == "sendMessage",
                "Wrong Telegram method or reminder contents",
            )
            fields = matches[0]["fields"]
            require(
                fields["chat_id"] == ["-1001234567890"]
                and "123.45 RUB" in fields["text"][0]
                and today.isoformat() in fields["text"][0],
                "Wrong Telegram destination, amount or due date",
            )
        return {"confirmed": sent, "requests": len(requests)}
    finally:
        await database.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(sys.argv[1], json.load(sys.stdin))), default=str))
