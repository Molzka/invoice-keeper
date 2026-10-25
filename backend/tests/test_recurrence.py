from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api import budget, payments
from app.delivery.schema import deliveries
from app.models import PaymentOccurrence
from app.schemas.payments import RecurringPaymentCreate
from app.services.payment_calendar import next_due_date, recurring_due_dates
from app.services.payment_source import PaymentSourceAdapter


@pytest.mark.parametrize(
    ("first", "periodicity", "interval", "through", "expected"),
    [
        ("2028-02-27", "daily", 2, "2028-03-02", ["2028-02-27", "2028-02-29", "2028-03-02"]),
        ("2027-12-24", "weekly", 2, "2028-01-21", ["2027-12-24", "2028-01-07", "2028-01-21"]),
        ("2027-12-31", "monthly", 2, "2028-04-30", ["2027-12-31", "2028-02-29", "2028-04-30"]),
        ("2028-02-29", "yearly", 2, "2032-02-29", ["2028-02-29", "2030-02-28", "2032-02-29"]),
        ("2026-10-25", "once", 1, "2027-10-25", ["2026-10-25"]),
    ],
)
def test_schedule_and_next_date_share_original_anchor(
    first, periodicity, interval, through, expected
):
    first = date.fromisoformat(first)
    dates = [date.fromisoformat(value) for value in expected]
    assert (
        recurring_due_dates(first, first.day, date.fromisoformat(through), periodicity, interval)
        == dates
    )
    for index, due in enumerate(dates):
        assert next_due_date(first, first.day, due, periodicity, interval) == due
        if index:
            between = date.fromordinal(dates[index - 1].toordinal() + 1)
            assert next_due_date(first, first.day, between, periodicity, interval) == due
    assert recurring_due_dates(
        first, first.day, dates[-1], periodicity, interval, start=dates[-1]
    ) == [dates[-1]]


@pytest.mark.parametrize("periodicity", ["daily", "weekly", "monthly", "yearly"])
def test_schedule_stops_at_maximum_calendar_date(periodicity):
    first = date(9999, 12, 30)
    assert next_due_date(first, 30, date.max, periodicity, 2) is None
    assert recurring_due_dates(first, 30, date.max, periodicity, 2) == [first]


@pytest.mark.parametrize("interval", [0, -1, 366, 1.5, True, "2", None])
def test_interval_validation(interval):
    with pytest.raises(ValidationError):
        RecurringPaymentCreate(
            title="Server",
            amount="10.00",
            currency="USD",
            first_due_date="2026-10-25",
            periodicity="weekly",
            recurrence_interval=interval,
        )


def test_old_monthly_payload_defaults_to_one_month():
    payment = RecurringPaymentCreate(
        title="Rent",
        amount="10.00",
        currency="USD",
        first_due_date="2026-10-25",
        periodicity="monthly",
    )
    assert payment.recurrence_interval == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("periodicity", "interval", "october", "december_count"),
    [
        ("daily", 10, [1, 11, 21, 31], 3),
        ("weekly", 2, [1, 15, 29], 2),
        ("monthly", 3, [1], 0),
        ("yearly", 1, [1], 0),
    ],
)
async def test_api_worker_summary_and_forecast_use_selected_schedule(
    app,
    client,
    create_user,
    login,
    monkeypatch,
    periodicity,
    interval,
    october,
    december_count,
):
    for module in (payments, budget):
        monkeypatch.setattr(module, "today_in_timezone", lambda _: date(2026, 10, 25))
    await create_user()
    auth = await login(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    created = await client.post(
        "/api/v1/recurring-payments",
        headers=headers,
        json={
            "title": "Custom schedule",
            "amount": "10.00",
            "currency": "RUB",
            "first_due_date": "2026-10-01",
            "periodicity": periodicity,
            "recurrence_interval": interval,
        },
    )
    assert created.status_code == 201, created.text
    payment = created.json()
    assert payment["recurrence_interval"] == interval
    assert payment["periodicity"] == periodicity
    rows = await client.get(
        "/api/v1/payment-occurrences",
        params={
            "recurring_payment_id": payment["id"],
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
        },
    )
    assert [item["due_date"] for item in rows.json()["items"]] == [
        f"2026-10-{day:02}" for day in october
    ]
    summary = await client.get("/api/v1/payments/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["totals"]["RUB"]["planned"] == f"{len(october) * 10}.00"
    forecast = await client.get("/api/v1/payments/budget?year=2026&month=12")
    assert forecast.status_code == 200, forecast.text
    assert forecast.json()["totals"]["RUB"]["forecast"] == f"{december_count * 10}.00"
    changed = await client.patch(
        f"/api/v1/recurring-payments/{payment['id']}",
        headers=headers,
        json={"amount": "12.00", "currency": "RUB"},
    )
    assert changed.status_code == 200, changed.text
    await client.post(
        "/api/v1/one-time-payments",
        headers=headers,
        json={
            "title": "Once",
            "amount": "1.00",
            "currency": "USD",
            "due_date": "2026-10-25",
        },
    )
    listing = await client.get("/api/v1/recurring-payments?periodicity=recurring&is_active=true")
    assert [item["id"] for item in listing.json()["items"]] == [payment["id"]]
    source = PaymentSourceAdapter()
    async with app.state.database.session_factory() as db:
        for _ in range(2):
            await source.ensure_payment_periods(
                db, UUID(payment["id"]), date(2026, 12, 1), date(2026, 12, 31)
            )
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(deliveries)) == await db.scalar(
            select(func.count()).select_from(PaymentOccurrence)
        )
    december = await client.get(
        "/api/v1/payment-occurrences",
        params={
            "recurring_payment_id": payment["id"],
            "date_from": "2026-12-01",
            "date_to": "2026-12-31",
        },
    )
    assert december.json()["total"] == december_count
    assert all(item["amount"] == "12.00" for item in december.json()["items"])
