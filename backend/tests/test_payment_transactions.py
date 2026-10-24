import asyncio
from calendar import monthrange
from datetime import date

import pytest
from sqlalchemy import delete, func, select

from app.delivery.schema import deliveries
from app.models import PaymentOccurrence, RecurringPayment
from app.services.payment_calendar import monthly_due_dates
from app.services.payment_periods import ensure_payment_periods
from app.services.payments import today_in_timezone

pytestmark = pytest.mark.asyncio


async def _create_old_payment(client, token, today):
    first_due = date(today.year - 1, 1, 31)
    response = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Old invoice",
            "amount": "10.00",
            "currency": "RUB",
            "first_due_date": first_due.isoformat(),
            "periodicity": "monthly",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201, response.text
    return response.json(), first_due


async def test_summary_waits_for_missing_period_and_worker_restores_it(
    client, create_user, login, app
):
    await create_user()
    authentication = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    payment_data, first_due = await _create_old_payment(client, authentication["csrf_token"], today)
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    expected = monthly_due_dates(first_due, 31, month_end)
    missing_due_date = expected[len(expected) // 2]
    async with app.state.database.session_factory() as db:
        rule = await db.get(RecurringPayment, payment_data["id"])
        missing_occurrence_id = await db.scalar(
            select(PaymentOccurrence.id).where(
                PaymentOccurrence.recurring_payment_id == rule.id,
                PaymentOccurrence.due_date == missing_due_date,
            )
        )
        await db.execute(
            delete(deliveries).where(deliveries.c.occurrence_id == missing_occurrence_id)
        )
        await db.execute(
            delete(PaymentOccurrence).where(
                PaymentOccurrence.recurring_payment_id == rule.id,
                PaymentOccurrence.due_date == missing_due_date,
            )
        )
        await db.commit()

    summary_url = (
        "/api/v1/payments/summary"
        f"?date_from={first_due.replace(day=1).isoformat()}&date_to={month_end.isoformat()}"
    )
    incomplete = await client.get(summary_url)
    assert incomplete.status_code == 503
    assert incomplete.json()["error"]["code"] == "PERIODS_NOT_READY"

    async with app.state.database.session_factory() as db:
        await ensure_payment_periods(db, payment_data["id"], today)
        await db.commit()
    recovered = await client.get(summary_url)
    assert recovered.status_code == 200, recovered.text


async def test_concurrent_period_restores_keep_one_row_per_rule_and_due_date(
    client, create_user, login, app
):
    await create_user()
    authentication = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    payment_data, first_due = await _create_old_payment(client, authentication["csrf_token"], today)
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    expected = monthly_due_dates(first_due, 31, month_end)
    missing = expected[len(expected) // 2]
    async with app.state.database.session_factory() as db:
        missing_occurrence_id = await db.scalar(
            select(PaymentOccurrence.id).where(
                PaymentOccurrence.recurring_payment_id == payment_data["id"],
                PaymentOccurrence.due_date == missing,
            )
        )
        await db.execute(
            delete(deliveries).where(deliveries.c.occurrence_id == missing_occurrence_id)
        )
        await db.execute(
            delete(PaymentOccurrence).where(
                PaymentOccurrence.recurring_payment_id == payment_data["id"],
                PaymentOccurrence.due_date == missing,
            )
        )
        await db.commit()

    async def restore():
        async with app.state.database.session_factory() as db:
            await ensure_payment_periods(db, payment_data["id"], today)
            await db.commit()

    await asyncio.gather(restore(), restore())
    async with app.state.database.session_factory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(PaymentOccurrence)
            .where(
                PaymentOccurrence.recurring_payment_id == payment_data["id"],
                PaymentOccurrence.due_date.between(first_due, month_end),
            )
        )
        assert count == len(expected)
