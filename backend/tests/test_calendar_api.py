"""The calendar uses the existing period API, including every page of a month."""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.delivery.schema import deliveries
from app.models import PaymentOccurrence, RecurringPayment
from app.services.payments import today_in_timezone

pytestmark = pytest.mark.asyncio


async def _seed_periods(app, specifications):
    """Bulk-load real monthly rules without making 100 separate HTTP mutations."""
    periods = []
    async with app.state.database.session_factory() as db:
        for index, specification in enumerate(specifications):
            due_date = specification["due_date"]
            rule = RecurringPayment(
                id=uuid4(),
                title=f"Calendar payment {index}",
                amount=Decimal(specification.get("amount", "123.45")),
                currency=specification.get("currency", "RUB"),
                first_due_date=due_date,
                periodicity="monthly",
                anchor_day=due_date.day,
            )
            db.add(rule)
            periods.append(
                PaymentOccurrence(
                    id=uuid4(),
                    recurring_payment_id=rule.id,
                    due_date=due_date,
                    status=specification.get("status", "unpaid"),
                    paid_on=specification.get("paid_on"),
                )
            )
        await db.flush()
        db.add_all(periods)
        await db.commit()
    return periods


@pytest.mark.parametrize("role", ["admin", "user"])
async def test_calendar_loads_every_page_of_a_month_for_both_roles(
    client, create_user, login, app, role
):
    await create_user("calendar_reader", role=role)
    today = today_in_timezone(app.state.settings.app_timezone)
    month_start = date(today.year - 1, 1, 1)
    month_end = date(today.year - 1, 1, 31)
    specifications = [
        {
            "due_date": month_start + timedelta(days=index % 31),
            "currency": ("RUB", "USD", "EUR")[index % 3],
            "amount": "999999999999.99",
        }
        for index in range(105)
    ]
    periods = await _seed_periods(
        app,
        [
            *specifications,
            {"due_date": month_start - timedelta(days=1)},
            {"due_date": month_end + timedelta(days=1)},
        ],
    )
    await login(client, "calendar_reader")
    filters = {"date_from": month_start.isoformat(), "date_to": month_end.isoformat()}
    collected = []
    for offset, page_size in ((0, 100), (100, 5), (105, 0)):
        response = await client.get(
            "/api/v1/payment-occurrences", params={**filters, "limit": 100, "offset": offset}
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert (page["total"], page["limit"], page["offset"]) == (105, 100, offset)
        assert len(page["items"]) == page_size
        collected.extend(page["items"])

    expected = sorted(periods[:105], key=lambda period: (period.due_date, period.id))
    assert [item["id"] for item in collected] == [str(period.id) for period in expected]
    assert len({item["id"] for item in collected}) == 105
    assert {item["currency"] for item in collected} == {"RUB", "USD", "EUR"}
    assert {item["amount"] for item in collected} == {"999999999999.99"}
    assert all(item["is_overdue"] and not item["paid_late"] for item in collected)


async def test_calendar_filters_use_inclusive_due_dates_and_preserve_money(
    client, create_user, login, app
):
    await create_user("calendar_reader", role="user")
    today = today_in_timezone(app.state.settings.app_timezone)
    first = date(today.year - 1, 2, 1)
    last = date(first.year, 2, monthrange(first.year, 2)[1])
    periods = await _seed_periods(
        app,
        [
            {"due_date": first, "amount": "0.01"},
            {
                "due_date": last,
                "amount": "999999999999.99",
                "status": "paid",
                "paid_on": last + timedelta(days=3),
            },
            {
                "due_date": first - timedelta(days=1),
                "status": "paid",
                "paid_on": first,
            },
            {"due_date": last + timedelta(days=1)},
            {"due_date": first, "currency": "USD"},
            {"due_date": last, "currency": "EUR"},
        ],
    )
    await login(client, "calendar_reader")
    filters = {"date_from": first.isoformat(), "date_to": last.isoformat(), "currency": "RUB"}
    response = await client.get("/api/v1/payment-occurrences", params=filters)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert response.json()["total"] == 2
    assert [item["id"] for item in items] == [str(periods[0].id), str(periods[1].id)]
    assert [item["amount"] for item in items] == ["0.01", "999999999999.99"]
    assert items[1]["paid_on"] > last.isoformat()
    assert items[1]["paid_late"] is True
    assert items[1]["days_late"] == 3

    for extra, expected_index in (
        ({"status": "unpaid"}, 0),
        ({"status": "unpaid", "is_overdue": "true"}, 0),
        ({"status": "paid", "is_overdue": "false"}, 1),
        ({"recurring_payment_id": str(periods[1].recurring_payment_id)}, 1),
    ):
        filtered = await client.get("/api/v1/payment-occurrences", params={**filters, **extra})
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["id"] == str(periods[expected_index].id)

    for currency, expected_index in (("USD", 4), ("EUR", 5)):
        filtered = await client.get(
            "/api/v1/payment-occurrences", params={**filters, "currency": currency}
        )
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["id"] == str(periods[expected_index].id)


async def test_stopped_rule_stays_in_calendar_and_user_can_open_and_pay_its_period(
    client, create_user, login, app
):
    await create_user()
    await create_user("calendar_reader", role="user")
    authentication = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    due_date = date(today.year - 1, 2, 1)
    created = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Stopped calendar rule",
            "amount": "10.20",
            "currency": "EUR",
            "first_due_date": due_date.isoformat(),
            "periodicity": "monthly",
        },
        headers={"X-CSRF-Token": authentication["csrf_token"]},
    )
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]
    filters = {
        "date_from": due_date.isoformat(),
        "date_to": due_date.isoformat(),
        "recurring_payment_id": payment_id,
    }
    before = await client.get("/api/v1/payment-occurrences", params=filters)
    assert before.status_code == 200, before.text
    assert before.json()["total"] == 1
    occurrence_id = before.json()["items"][0]["id"]
    stopped = await client.delete(
        f"/api/v1/recurring-payments/{payment_id}",
        headers={"X-CSRF-Token": authentication["csrf_token"]},
    )
    assert stopped.status_code == 204, stopped.text

    user_authentication = await login(client, "calendar_reader")
    after = await client.get("/api/v1/payment-occurrences", params=filters)
    assert after.status_code == 200, after.text
    assert after.json()["total"] == 1
    retained = after.json()["items"][0]
    assert retained["id"] == occurrence_id
    assert retained["recurring_payment_is_active"] is False
    detail = await client.get(f"/api/v1/payment-occurrences/{occurrence_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json() == retained

    paid = await client.patch(
        f"/api/v1/payment-occurrences/{occurrence_id}",
        json={"status": "paid", "paid_on": today.isoformat()},
        headers={"X-CSRF-Token": user_authentication["csrf_token"]},
    )
    assert paid.status_code == 200, paid.text
    calendar = await client.get("/api/v1/payment-occurrences", params=filters)
    assert calendar.status_code == 200, calendar.text
    assert calendar.json()["items"] == [paid.json()]
    assert paid.json()["recurring_payment_is_active"] is False
    assert paid.json()["status"] == "paid"


async def test_empty_future_calendar_does_not_generate_periods_or_reminders(
    client, create_user, login, app
):
    await create_user()
    authentication = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    created = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Active monthly rule",
            "amount": "12.30",
            "currency": "RUB",
            "first_due_date": today.isoformat(),
            "periodicity": "monthly",
        },
        headers={"X-CSRF-Token": authentication["csrf_token"]},
    )
    assert created.status_code == 201, created.text

    async def counts():
        async with app.state.database.session_factory() as db:
            return (
                await db.scalar(select(func.count()).select_from(PaymentOccurrence)),
                await db.scalar(select(func.count()).select_from(deliveries)),
            )

    before = await counts()
    assert before == (1, 1)
    future_start = date(today.year + 1, 2, 1)
    future_end = date(future_start.year, 2, monthrange(future_start.year, 2)[1])
    for offset in (0, 100, 0):
        response = await client.get(
            "/api/v1/payment-occurrences",
            params={
                "date_from": future_start.isoformat(),
                "date_to": future_end.isoformat(),
                "limit": 100,
                "offset": offset,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"items": [], "total": 0, "limit": 100, "offset": offset}
    assert await counts() == before
