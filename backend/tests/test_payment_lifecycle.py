from datetime import date

import pytest

from app.services.payment_periods import ensure_payment_periods

pytestmark = pytest.mark.asyncio
TODAY = date(2026, 10, 23)


@pytest.fixture(autouse=True)
def business_day(monkeypatch):
    for module in ("payments", "payment_lifecycle", "budget", "receipts"):
        monkeypatch.setattr(f"app.api.{module}.today_in_timezone", lambda _timezone: TODAY)


async def authenticate(client, create_user, login):
    await create_user()
    auth = await login(client)
    return {"X-CSRF-Token": auth["csrf_token"]}


async def create_once(client, headers, title="One time", amount="45000.50", currency="RUB"):
    response = await client.post(
        "/api/v1/one-time-payments",
        json={"title": title, "amount": amount, "currency": currency, "due_date": "2026-10-20"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_one_time_payment_never_repeats_and_cancelled_tombstone_is_not_regenerated(
    client, app, create_user, login
):
    headers = await authenticate(client, create_user, login)
    item = await create_once(client, headers)
    assert item["periodicity"] == "once"
    async with app.state.database.session_factory() as db:
        await ensure_payment_periods(db, item["recurring_payment_id"], date(2028, 5, 1))
        await db.commit()
    assert (await client.get("/api/v1/payment-occurrences")).json()["total"] == 1
    assert (
        await client.delete(f"/api/v1/payment-occurrences/{item['id']}", headers=headers)
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/payment-occurrences/{item['id']}", headers=headers)
    ).status_code == 204
    assert (await client.get("/api/v1/payment-occurrences")).json()["total"] == 0
    history = (await client.get("/api/v1/payment-occurrences?include_cancelled=true")).json()
    assert history["total"] == 1 and history["items"][0]["is_cancelled"] is True
    rules = (await client.get("/api/v1/recurring-payments?include_archived=true")).json()["items"]
    assert rules[0]["is_archived"] is True and rules[0]["next_due_date"] is None
    assert (await client.get("/api/v1/payments/summary")).json()["totals"]["RUB"][
        "planned"
    ] == "0.00"
    changed = await client.patch(
        f"/api/v1/payment-occurrences/{item['id']}",
        json={"status": "paid", "paid_on": "2026-10-23"},
        headers=headers,
    )
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "PAYMENT_CANCELLED"
    events = (await client.get("/api/v1/audit-events?action=payment.period_deleted")).json()
    assert events["total"] == 1


async def test_archive_preserves_paid_receipt_and_cancels_unpaid_snapshots_in_budget(
    client, create_user, login
):
    headers = await authenticate(client, create_user, login)
    response = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Monthly",
            "amount": "10.00",
            "currency": "USD",
            "first_due_date": "2026-09-20",
            "periodicity": "monthly",
        },
        headers=headers,
    )
    rule = response.json()
    rows = (
        await client.get(f"/api/v1/payment-occurrences?recurring_payment_id={rule['id']}")
    ).json()["items"]
    paid = rows[0]
    assert (
        await client.patch(
            f"/api/v1/payment-occurrences/{paid['id']}",
            json={"status": "paid", "paid_on": "2026-09-20"},
            headers=headers,
        )
    ).status_code == 200
    assert (
        await client.put(
            f"/api/v1/payment-occurrences/{paid['id']}/receipt",
            json={"url": "https://example.com/receipt"},
            headers=headers,
        )
    ).status_code == 200
    protected = await client.delete(f"/api/v1/payment-occurrences/{paid['id']}", headers=headers)
    assert protected.status_code == 409
    assert (
        await client.post(f"/api/v1/recurring-payments/{rule['id']}/archive", headers=headers)
    ).status_code == 204
    assert (await client.get("/api/v1/recurring-payments")).json()["total"] == 0
    visible = (await client.get("/api/v1/payment-occurrences")).json()["items"]
    assert [item["id"] for item in visible] == [paid["id"]]
    assert (await client.get(f"/api/v1/payment-occurrences/{paid['id']}/receipt")).json()[
        "url"
    ] == "https://example.com/receipt"
    budget = (await client.get("/api/v1/payments/budget?year=2026")).json()["totals"]["USD"]
    assert budget == {
        "planned": "10.00",
        "paid": "10.00",
        "unpaid": "0.00",
        "overdue": "0.00",
        "forecast": "0.00",
    }


async def test_amount_snapshot_budget_uses_period_currency_and_receipt_listing_filters_before_pagination(
    client, create_user, login
):
    headers = await authenticate(client, create_user, login)
    first = await create_once(client, headers, title="Invoice A")
    await create_once(client, headers, title="Invoice B")
    updated = await client.patch(
        f"/api/v1/payment-occurrences/{first['id']}/amount",
        json={"amount": "12.50", "currency": "EUR"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    saved = await client.put(
        f"/api/v1/payment-occurrences/{first['id']}/receipt",
        json={"url": "https://example.com/proof"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    page = (
        await client.get("/api/v1/payment-receipts?kind=link&currency=EUR&query=Invoice&limit=1")
    ).json()
    assert page["total"] == 1 and len(page["items"]) == 1
    assert page["items"][0]["occurrence"]["id"] == first["id"]
    assert page["items"][0]["receipt"]["kind"] == "link"
    assert (await client.get("/api/v1/payment-receipts?kind=missing")).json()["total"] == 1
    budget = (await client.get("/api/v1/payments/budget?year=2026&month=10")).json()
    assert budget["totals"]["EUR"]["planned"] == "12.50"
    assert budget["totals"]["RUB"]["planned"] == "45000.50"
    events = (await client.get("/api/v1/audit-events?action=payment.amount_changed")).json()
    assert events["total"] == 1


async def test_lifecycle_requires_admin_csrf_and_does_not_allow_extra_fields(
    client, create_user, login
):
    headers = await authenticate(client, create_user, login)
    item = await create_once(client, headers)
    assert (await client.delete(f"/api/v1/payment-occurrences/{item['id']}")).status_code == 403
    extra = await client.post(
        "/api/v1/one-time-payments",
        json={
            "title": "X",
            "amount": "1.00",
            "currency": "RUB",
            "due_date": "2026-10-23",
            "is_cancelled": True,
        },
        headers=headers,
    )
    assert extra.status_code == 422
    await create_user("member", role="user")
    auth = await login(client, "member")
    denied = await client.delete(
        f"/api/v1/payment-occurrences/{item['id']}", headers={"X-CSRF-Token": auth["csrf_token"]}
    )
    assert denied.status_code == 403
    assert (await client.get("/api/v1/payment-receipts")).status_code == 200
