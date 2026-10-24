from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import RecurringPayment
from app.services.payment_calendar import monthly_due_dates
from app.services.payment_periods import active_generation_end, ensure_payment_periods
from app.services.payments import today_in_timezone

pytestmark = pytest.mark.asyncio


async def _create_payment(client, token, *, amount="10.00", first_due_date="2026-01-31"):
    return await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Office",
            "amount": amount,
            "currency": "RUB",
            "first_due_date": first_due_date,
            "periodicity": "monthly",
        },
        headers={"X-CSRF-Token": token},
    )


async def test_payment_routes_enforce_access_and_create_complete_period_history(
    client, create_user, login, app
):
    await create_user()
    user = await create_user("ordinary", role="user")
    today = today_in_timezone(app.state.settings.app_timezone)
    first_due_date = date(today.year - 1, 1, 31)
    payload = {
        "title": "Office",
        "amount": "10.00",
        "currency": "RUB",
        "first_due_date": first_due_date.isoformat(),
        "periodicity": "monthly",
    }

    denied = await client.post("/api/v1/recurring-payments", json=payload)
    assert denied.status_code == 401

    user_auth = await login(client, "ordinary")
    assert (
        await client.post(
            "/api/v1/recurring-payments",
            json=payload,
            headers={"X-CSRF-Token": user_auth["csrf_token"]},
        )
    ).status_code == 403

    admin_auth = await login(client)
    created = await client.post(
        "/api/v1/recurring-payments",
        json=payload,
        headers={"X-CSRF-Token": admin_auth["csrf_token"]},
    )
    assert created.status_code == 201, created.text
    payment = created.json()
    assert payment["amount"] == "10.00"
    assert payment["anchor_day"] == 31

    async with app.state.database.session_factory() as db:
        rule = await db.get(RecurringPayment, payment["id"])
        expected = monthly_due_dates(
            first_due_date,
            31,
            active_generation_end(rule, today),
        )
        rows = await client.get("/api/v1/payment-occurrences?recurring_payment_id=" + payment["id"])
        assert rows.status_code == 200
        actual_dates = [item["due_date"] for item in rows.json()["items"]]
        assert actual_dates == [item.isoformat() for item in expected]
        assert rows.json()["total"] == len(expected)
        empty_page = await client.get("/api/v1/recurring-payments?limit=1&offset=1")
        assert empty_page.json() == {"items": [], "total": 1, "limit": 1, "offset": 1}

    assert user.role == "user"
    await login(client, "ordinary")
    assert (await client.get("/api/v1/recurring-payments")).status_code == 200


async def test_payment_state_and_summary_follow_due_date(client, create_user, login, app):
    await create_user()
    admin_auth = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    due_date = date(today.year - 1, 1, 31)
    created = await _create_payment(
        client,
        admin_auth["csrf_token"],
        first_due_date=due_date.isoformat(),
    )
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]
    periods = (
        await client.get(
            f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}&date_from={due_date.isoformat()}&date_to={due_date.isoformat()}"
        )
    ).json()
    assert periods["total"] == 1
    period = periods["items"][0]
    period_id = period["id"]

    late_payment_date = due_date + timedelta(days=3)
    patched = await client.patch(
        f"/api/v1/payment-occurrences/{period_id}",
        json={"status": "paid", "paid_on": late_payment_date.isoformat()},
        headers={"X-CSRF-Token": admin_auth["csrf_token"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["paid_late"] is True
    assert patched.json()["days_late"] == 3
    assert patched.json()["due_date"] == due_date.isoformat()
    detail = await client.get(f"/api/v1/payment-occurrences/{period_id}")
    assert detail.status_code == 200
    assert detail.json()["paid_on"] == late_payment_date.isoformat()

    async with app.state.database.session_factory() as db:
        await ensure_payment_periods(db, payment_id, today)
        await db.commit()
    assert (await client.get(f"/api/v1/payment-occurrences/{period_id}")).json()["paid_on"] == (
        late_payment_date.isoformat()
    )
    paid_filter = await client.get(
        "/api/v1/payment-occurrences"
        f"?date_from={due_date.isoformat()}&date_to={due_date.isoformat()}"
        f"&status=paid&currency=RUB&recurring_payment_id={payment_id}&is_overdue=false"
        "&limit=1&offset=0"
    )
    assert paid_filter.status_code == 200
    assert paid_filter.json()["total"] == 1
    assert paid_filter.json()["items"][0]["paid_late"] is True
    overdue_filter = await client.get(
        f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}&is_overdue=true"
    )
    assert overdue_filter.json()["total"] > 0
    assert period_id not in {item["id"] for item in overdue_filter.json()["items"]}

    corrected = await client.patch(
        f"/api/v1/payment-occurrences/{period_id}",
        json={"status": "paid", "paid_on": due_date.isoformat()},
        headers={"X-CSRF-Token": admin_auth["csrf_token"]},
    )
    assert corrected.status_code == 200
    assert corrected.json()["paid_late"] is False
    assert corrected.json()["days_late"] == 0
    repeated = await client.patch(
        f"/api/v1/payment-occurrences/{period_id}",
        json={"status": "paid", "paid_on": late_payment_date.isoformat()},
        headers={"X-CSRF-Token": admin_auth["csrf_token"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["paid_late"] is True

    summary = await client.get(
        "/api/v1/payments/summary"
        f"?date_from={due_date.replace(day=1).isoformat()}"
        f"&date_to={date(today.year - 1, 1, monthrange(today.year - 1, 1)[1]).isoformat()}"
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["totals"]["RUB"] == {
        "planned": "10.00",
        "paid": "10.00",
        "unpaid": "0.00",
        "overdue": "0.00",
    }
    assert summary.json()["totals"]["USD"]["planned"] == "0.00"
    assert summary.json()["totals"]["EUR"]["planned"] == "0.00"

    cancelled = await client.patch(
        f"/api/v1/payment-occurrences/{period_id}",
        json={"status": "unpaid", "paid_on": None},
        headers={"X-CSRF-Token": admin_auth["csrf_token"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["paid_on"] is None
    assert cancelled.json()["is_overdue"] is True
    assert (
        await client.get(
            f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}&is_overdue=true"
        )
    ).json()["total"] >= 1

    summary = await client.get(
        "/api/v1/payments/summary"
        f"?date_from={due_date.replace(day=1).isoformat()}"
        f"&date_to={date(today.year - 1, 1, monthrange(today.year - 1, 1)[1]).isoformat()}"
    )
    assert summary.json()["totals"]["RUB"] == {
        "planned": "10.00",
        "paid": "0.00",
        "unpaid": "10.00",
        "overdue": "10.00",
    }


async def test_payment_list_paginates_over_one_hundred_periods_and_summary_sums_all(
    client, create_user, login, app
):
    await create_user()
    authentication = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    first_due = date(today.year - 10, 1, 31)
    amount = "999999999999.99"
    created = await _create_payment(
        client,
        authentication["csrf_token"],
        amount=amount,
        first_due_date=first_due.isoformat(),
    )
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    expected_dates = monthly_due_dates(first_due, 31, month_end)
    assert len(expected_dates) > 100

    page = await client.get(
        f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}&limit=100&offset=0"
    )
    last_page = await client.get(
        f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}&limit=100&offset=100"
    )
    assert page.json()["total"] == len(expected_dates)
    assert len(page.json()["items"]) == 100
    assert len(last_page.json()["items"]) == len(expected_dates) - 100

    summary = await client.get(
        "/api/v1/payments/summary"
        f"?date_from={first_due.replace(day=1).isoformat()}&date_to={month_end.isoformat()}"
    )
    assert summary.status_code == 200, summary.text
    expected_total = format(Decimal(amount) * len(expected_dates), ".2f")
    assert summary.json()["totals"]["RUB"]["planned"] == expected_total
    assert summary.json()["totals"]["RUB"]["unpaid"] == expected_total


async def test_delete_stops_future_generation_and_preserves_existing_periods(
    client, create_user, login, app
):
    await create_user()
    user = await create_user("ordinary", role="user")
    user_auth = await login(client, "ordinary")
    today = today_in_timezone(app.state.settings.app_timezone)
    future_date = date(today.year + 1, 1, 31)
    payload = {
        "title": "Future office",
        "amount": "10.00",
        "currency": "RUB",
        "first_due_date": future_date.isoformat(),
        "periodicity": "monthly",
    }
    assert (
        await client.post(
            "/api/v1/recurring-payments",
            json=payload,
            headers={"X-CSRF-Token": user_auth["csrf_token"]},
        )
    ).status_code == 403

    admin_auth = await login(client)
    created = await client.post(
        "/api/v1/recurring-payments",
        json=payload,
        headers={"X-CSRF-Token": admin_auth["csrf_token"]},
    )
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]
    assert (
        await client.get(f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}")
    ).json()["total"] == 1

    path = f"/api/v1/recurring-payments/{payment_id}"
    headers = {"X-CSRF-Token": admin_auth["csrf_token"]}
    assert (await client.delete(path, headers=headers)).status_code == 204
    assert (await client.delete(path, headers=headers)).status_code == 204
    stopped = (await client.get("/api/v1/recurring-payments?is_active=false")).json()["items"][0]
    assert stopped["is_active"] is False
    assert stopped["next_due_date"] is None
    assert (
        await client.get(f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}")
    ).json()["total"] == 1
    assert (
        await client.delete(
            "/api/v1/recurring-payments/00000000-0000-0000-0000-000000000001",
            headers=headers,
        )
    ).status_code == 404
    assert user.role == "user"


async def test_payment_inputs_and_period_filters_use_shared_error_shape(client, create_user, login):
    await create_user()
    authentication = await login(client)
    bad_amount = await _create_payment(client, authentication["csrf_token"], amount="1.234")
    assert bad_amount.status_code == 422
    detail = bad_amount.json()["error"]["details"][0]
    assert detail["field"] == "amount"
    assert detail["code"] == "INVALID_MONEY_FORMAT"

    one_boundary = await client.get("/api/v1/payments/summary?date_from=2026-10-01")
    assert one_boundary.status_code == 422
    assert one_boundary.json()["error"]["code"] == "VALIDATION_ERROR"

    bad_range = await client.get(
        "/api/v1/payment-occurrences?date_from=2026-11-01&date_to=2026-10-01"
    )
    assert bad_range.status_code == 422
    assert bad_range.json()["error"]["code"] == "VALIDATION_ERROR"
    default_summary = await client.get("/api/v1/payments/summary")
    today = today_in_timezone("Europe/Moscow")
    assert default_summary.status_code == 200
    assert default_summary.json()["date_from"] == date(today.year, today.month, 1).isoformat()
    assert (
        default_summary.json()["date_to"]
        == date(today.year, today.month, monthrange(today.year, today.month)[1]).isoformat()
    )
    assert default_summary.json()["totals"]["RUB"]["planned"] == "0.00"

    csrf = {"X-CSRF-Token": authentication["csrf_token"]}
    inconsistent = await client.patch(
        "/api/v1/payment-occurrences/00000000-0000-0000-0000-000000000001",
        json={"status": "paid", "paid_on": None},
        headers=csrf,
    )
    assert inconsistent.status_code == 422

    created = await _create_payment(client, authentication["csrf_token"])
    assert created.status_code == 201, created.text
    period = (
        await client.get(f"/api/v1/payment-occurrences?recurring_payment_id={created.json()['id']}")
    ).json()["items"][0]
    future = await client.patch(
        f"/api/v1/payment-occurrences/{period['id']}",
        json={
            "status": "paid",
            "paid_on": (today_in_timezone("Europe/Moscow") + timedelta(days=1)).isoformat(),
        },
        headers=csrf,
    )
    assert future.status_code == 422
    assert future.json()["error"]["details"][0]["code"] == "FUTURE_PAYMENT_DATE"

    for query in ("limit=0", "limit=101", "offset=-1"):
        invalid_page = await client.get(f"/api/v1/payment-occurrences?{query}")
        assert invalid_page.status_code == 422
