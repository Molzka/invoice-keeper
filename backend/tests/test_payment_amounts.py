from asyncio import gather
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.delivery.schema import deliveries
from app.models import PaymentOccurrence, RecurringPayment
from app.services.payment_periods import ensure_payment_periods
from app.services.payment_source import make_source

pytestmark = pytest.mark.asyncio
TODAY = date(2027, 1, 23)


@pytest.fixture(autouse=True)
def fixed_payment_day(monkeypatch):
    monkeypatch.setattr("app.api.payments.today_in_timezone", lambda _timezone: TODAY)


async def setup_payment(client, create_user, login, first_due="2026-12-31"):
    await create_user()
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    response = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Office",
            "amount": "10.00",
            "currency": "RUB",
            "first_due_date": first_due,
            "periodicity": "monthly",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json(), headers


async def periods(client, payment_id):
    response = await client.get(
        f"/api/v1/payment-occurrences?recurring_payment_id={payment_id}&limit=100"
    )
    assert response.status_code == 200, response.text
    return {row["due_date"]: row for row in response.json()["items"]}


async def test_amount_routes_require_admin_csrf_origin_and_json(client, create_user, login):
    payload = {"amount": "12.50", "currency": "USD"}
    unknown = uuid4()
    for path in (f"/recurring-payments/{unknown}", f"/payment-occurrences/{unknown}/amount"):
        denied = await client.patch("/api/v1" + path, json=payload)
        assert denied.status_code == 401

    rule, headers = await setup_payment(client, create_user, login)
    period = (await periods(client, rule["id"]))["2027-01-31"]
    paths = (f"/recurring-payments/{rule['id']}", f"/payment-occurrences/{period['id']}/amount")
    for path in paths:
        url = "/api/v1" + path
        assert (await client.patch(url, json=payload)).status_code == 403
        assert (
            await client.patch(url, json=payload, headers={"X-CSRF-Token": "wrong"})
        ).status_code == 403
        assert (
            await client.patch(
                url, json=payload, headers={**headers, "Origin": "https://foreign.invalid"}
            )
        ).status_code == 403
        assert (
            await client.patch(
                url,
                content="amount=12.50",
                headers={
                    **headers,
                    "Content-Type": "text/plain",
                },
            )
        ).status_code == 415
        origin = client.headers.pop("Origin")
        try:
            assert (await client.patch(url, json=payload, headers=headers)).status_code == 403
        finally:
            client.headers["Origin"] = origin

    await create_user("ordinary", role="user")
    ordinary = await login(client, "ordinary")
    for path in paths:
        response = await client.patch(
            "/api/v1" + path, json=payload, headers={"X-CSRF-Token": ordinary["csrf_token"]}
        )
        assert response.status_code == 403
    untouched = (await periods(client, rule["id"]))["2027-01-31"]
    assert (untouched["amount"], untouched["currency"]) == ("10.00", "RUB")


async def test_amount_routes_validate_exact_payload_without_mutating_data(
    client, create_user, login
):
    rule, headers = await setup_payment(client, create_user, login)
    period = (await periods(client, rule["id"]))["2027-01-31"]
    paths = (f"/recurring-payments/{rule['id']}", f"/payment-occurrences/{period['id']}/amount")
    invalid = [
        {},
        {"amount": "12.50"},
        {"currency": "USD"},
        *(
            {"amount": value, "currency": "USD"}
            for value in [
                12.50,
                True,
                None,
                "0.00",
                "-1.00",
                "1.0",
                "1,00",
                "1.001",
                "1e2",
                "1.00 ",
                "1000000000000.00",
            ]
        ),
        {"amount": "12.50", "currency": "CAD"},
        {"amount": "12.50", "currency": "USD", "status": "paid"},
        {"amount": "12.50", "currency": "USD", "due_date": "2027-02-01"},
        {"amount": "12.50", "currency": "USD", "effective_from": "2026-01-01"},
    ]
    for path in paths:
        for payload in invalid:
            response = await client.patch("/api/v1" + path, json=payload, headers=headers)
            assert response.status_code == 422, (path, payload, response.text)
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        response = await client.patch(
            "/api/v1" + path + "?extra=1",
            json={"amount": "12.50", "currency": "USD"},
            headers=headers,
        )
        assert response.status_code == 422
        response = await client.patch(
            "/api/v1" + path,
            content="{bad-json",
            headers={
                **headers,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 400

    old_route = await client.patch(
        f"/api/v1/payment-occurrences/{period['id']}",
        json={
            "status": "unpaid",
            "paid_on": None,
            "amount": "12.50",
        },
        headers=headers,
    )
    assert old_route.status_code == 422
    unknown = uuid4()
    for path in (f"/recurring-payments/{unknown}", f"/payment-occurrences/{unknown}/amount"):
        response = await client.patch(
            "/api/v1" + path, json={"amount": "12.50", "currency": "USD"}, headers=headers
        )
        assert response.status_code == 404
    current = (await periods(client, rule["id"]))["2027-01-31"]
    assert current["amount"] == rule["amount"] == "10.00"
    assert current["currency"] == "RUB" and current["amount_is_custom"] is False


async def test_individual_edit_moves_only_target_totals_and_reminder_snapshot(
    app,
    client,
    create_user,
    login,
):
    rule, headers = await setup_payment(client, create_user, login, first_due="2027-01-10")
    before = await periods(client, rule["id"])
    january = before["2027-01-10"]
    path = f"/api/v1/payment-occurrences/{january['id']}/amount"
    noop = await client.patch(path, json={"amount": "10.00", "currency": "RUB"}, headers=headers)
    assert noop.status_code == 200 and noop.json()["amount_is_custom"] is False
    edited = await client.patch(path, json={"amount": "12.50", "currency": "EUR"}, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()["amount_is_custom"] is True
    assert edited.json()["due_date"] == "2027-01-10"
    rows = await periods(client, rule["id"])
    assert rows["2027-02-10"] == before["2027-02-10"]
    async with app.state.database.session_factory() as db:
        current_rule = await db.get(RecurringPayment, UUID(rule["id"]))
        assert (current_rule.amount, current_rule.currency) == (Decimal("10.00"), "RUB")
        snapshot = await make_source().occurrence(db, UUID(rule["id"]), UUID(january["id"]))
        assert (snapshot.amount, snapshot.currency) == (Decimal("12.50"), "EUR")
    summary = (await client.get("/api/v1/payments/summary")).json()["totals"]
    assert summary["EUR"] == {
        "planned": "12.50",
        "paid": "0.00",
        "unpaid": "12.50",
        "overdue": "12.50",
    }
    assert summary["RUB"]["planned"] == summary["USD"]["planned"] == "0.00"
    for currency, count in (("EUR", 1), ("RUB", 0)):
        filtered = await client.get(
            f"/api/v1/payment-occurrences?currency={currency}&date_from=2027-01-01&date_to=2027-01-31"
        )
        assert filtered.json()["total"] == count

    paid = await client.patch(
        f"/api/v1/payment-occurrences/{january['id']}",
        json={"status": "paid", "paid_on": TODAY.isoformat()},
        headers=headers,
    )
    assert paid.status_code == 200
    protected = await client.patch(
        path, json={"amount": "99.00", "currency": "USD"}, headers=headers
    )
    assert protected.status_code == 409
    assert protected.json()["error"]["code"] == "PAYMENT_ALREADY_PAID"
    saved = (await periods(client, rule["id"]))["2027-01-10"]
    assert (saved["amount"], saved["currency"], saved["paid_on"]) == ("12.50", "EUR", "2027-01-23")
    paid_total = (await client.get("/api/v1/payments/summary")).json()["totals"]["EUR"]
    assert paid_total == {"planned": "12.50", "paid": "12.50", "unpaid": "0.00", "overdue": "0.00"}


async def test_recurring_edit_preserves_history_paid_and_individual_prices(
    app,
    client,
    create_user,
    login,
    monkeypatch,
):
    rule, headers = await setup_payment(client, create_user, login)
    async with app.state.database.session_factory() as db:
        await ensure_payment_periods(db, UUID(rule["id"]), TODAY, through=date(2027, 4, 30))
        await db.commit()
    before = await periods(client, rule["id"])
    february, march = before["2027-02-28"], before["2027-03-31"]
    custom = await client.patch(
        f"/api/v1/payment-occurrences/{february['id']}/amount",
        json={"amount": "15.25", "currency": "EUR"},
        headers=headers,
    )
    assert custom.status_code == 200
    prepaid = await client.patch(
        f"/api/v1/payment-occurrences/{march['id']}",
        json={"status": "paid", "paid_on": "2027-01-20"},
        headers=headers,
    )
    assert prepaid.status_code == 200
    result = await client.patch(
        f"/api/v1/recurring-payments/{rule['id']}",
        json={"amount": "20.50", "currency": "USD"},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["effective_from"] == "2027-02-01"
    assert (data["updated_periods"], data["preserved_custom_periods"]) == (1, 1)
    assert (data["payment"]["amount"], data["payment"]["currency"]) == ("20.50", "USD")
    assert data["payment"]["amount_effective_from"] == "2027-02-01"
    assert data["payment"]["anchor_day"] == 31
    after = await periods(client, rule["id"])
    for day in ("2026-12-31", "2027-01-31"):
        assert after[day] == before[day]
    assert after["2027-02-28"] == custom.json()
    assert after["2027-03-31"] == prepaid.json()
    assert (after["2027-04-30"]["amount"], after["2027-04-30"]["currency"]) == ("20.50", "USD")
    assert after["2027-04-30"]["amount_is_custom"] is False
    noop = await client.patch(
        f"/api/v1/recurring-payments/{rule['id']}",
        json={"amount": "20.50", "currency": "USD"},
        headers=headers,
    )
    assert noop.status_code == 200
    assert noop.json()["updated_periods"] == noop.json()["preserved_custom_periods"] == 0
    assert noop.json()["effective_from"] == "2027-02-01"
    async with app.state.database.session_factory() as db:
        await ensure_payment_periods(db, UUID(rule["id"]), TODAY, through=date(2027, 5, 31))
        await db.commit()
    generated = await periods(client, rule["id"])
    assert list(generated) == [
        "2026-12-31",
        "2027-01-31",
        "2027-02-28",
        "2027-03-31",
        "2027-04-30",
        "2027-05-31",
    ]
    assert (generated["2027-05-31"]["amount"], generated["2027-05-31"]["currency"]) == (
        "20.50",
        "USD",
    )
    monkeypatch.setattr("app.api.payments.today_in_timezone", lambda _timezone: date(2027, 5, 23))
    summary = (
        await client.get("/api/v1/payments/summary?date_from=2026-12-01&date_to=2027-05-31")
    ).json()
    assert summary["totals"]["RUB"]["planned"] == "30.00"
    assert summary["totals"]["RUB"]["paid"] == "10.00"
    assert summary["totals"]["EUR"]["planned"] == "15.25"
    assert summary["totals"]["USD"]["planned"] == "41.00"


async def test_regular_edit_restores_missing_history_at_old_price_first(
    app, client, create_user, login
):
    rule, headers = await setup_payment(client, create_user, login, first_due="2026-10-31")
    original = (await periods(client, rule["id"]))["2026-12-31"]
    async with app.state.database.session_factory() as db:
        identity = UUID(original["id"])
        await db.execute(delete(deliveries).where(deliveries.c.occurrence_id == identity))
        await db.execute(delete(PaymentOccurrence).where(PaymentOccurrence.id == identity))
        await db.commit()
    not_ready = await client.get("/api/v1/payments/summary?date_from=2026-10-01&date_to=2027-01-31")
    assert not_ready.status_code == 503
    result = await client.patch(
        f"/api/v1/recurring-payments/{rule['id']}",
        json={"amount": "22.25", "currency": "USD"},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    restored = (await periods(client, rule["id"]))["2026-12-31"]
    assert restored["id"] != original["id"]
    assert (restored["amount"], restored["currency"]) == ("10.00", "RUB")
    ready = await client.get("/api/v1/payments/summary?date_from=2026-10-01&date_to=2027-01-31")
    assert ready.status_code == 200
    assert ready.json()["totals"]["RUB"]["planned"] == "40.00"
    assert ready.json()["totals"]["USD"]["planned"] == "0.00"


async def test_stopped_rule_keeps_individual_unpaid_editing_available(client, create_user, login):
    rule, headers = await setup_payment(client, create_user, login)
    period = (await periods(client, rule["id"]))["2027-01-31"]
    assert (
        await client.delete(f"/api/v1/recurring-payments/{rule['id']}", headers=headers)
    ).status_code == 204
    denied = await client.patch(
        f"/api/v1/recurring-payments/{rule['id']}",
        json={"amount": "30.00", "currency": "USD"},
        headers=headers,
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "RECURRING_PAYMENT_STOPPED"
    changed = await client.patch(
        f"/api/v1/payment-occurrences/{period['id']}/amount",
        json={"amount": "30.00", "currency": "USD"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["recurring_payment_is_active"] is False


async def test_concurrent_payment_and_amount_edit_never_changes_an_already_paid_snapshot(
    client,
    create_user,
    login,
):
    rule, headers = await setup_payment(client, create_user, login)
    period = (await periods(client, rule["id"]))["2027-01-31"]
    path = f"/api/v1/payment-occurrences/{period['id']}"
    paid, changed = await gather(
        client.patch(path, json={"status": "paid", "paid_on": TODAY.isoformat()}, headers=headers),
        client.patch(
            path + "/amount", json={"amount": "55.25", "currency": "EUR"}, headers=headers
        ),
    )
    assert paid.status_code == 200, paid.text
    assert changed.status_code in (200, 409), changed.text
    final = (await client.get(path)).json()
    expected = ("55.25", "EUR") if changed.status_code == 200 else ("10.00", "RUB")
    assert (final["amount"], final["currency"]) == expected
    assert final["status"] == "paid" and final["paid_on"] == TODAY.isoformat()


async def test_recurring_amount_recovery_uses_configured_timezone_for_reminders(
    app, client, create_user, login
):
    from app.delivery.queue import reminder_at

    app.state.settings.app_timezone = "Asia/Tokyo"
    rule, headers = await setup_payment(client, create_user, login)
    period = (await periods(client, rule["id"]))["2027-01-31"]
    async with app.state.database.session_factory() as db:
        await db.execute(delete(deliveries).where(deliveries.c.occurrence_id == UUID(period["id"])))
        await db.execute(
            delete(PaymentOccurrence).where(PaymentOccurrence.id == UUID(period["id"]))
        )
        await db.commit()

    response = await client.patch(
        f"/api/v1/recurring-payments/{rule['id']}",
        json={"amount": "20.00", "currency": "USD"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    restored = (await periods(client, rule["id"]))["2027-01-31"]
    async with app.state.database.session_factory() as db:
        scheduled = await db.scalar(
            select(deliveries.c.scheduled_at).where(
                deliveries.c.occurrence_id == UUID(restored["id"])
            )
        )
    assert scheduled == reminder_at(date(2027, 1, 31), "Asia/Tokyo")
    assert scheduled != reminder_at(date(2027, 1, 31), "Europe/Moscow")
