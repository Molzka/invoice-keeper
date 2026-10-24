from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.api import budget
from app.delivery.schema import deliveries
from app.models import PaymentOccurrence, RecurringPayment

from .test_auth import assert_error

pytestmark = pytest.mark.asyncio
PATH = "/api/v1/payments/budget"
CURRENCIES = ("RUB", "USD", "EUR")
FIELDS = ("planned", "paid", "unpaid", "overdue", "forecast")


def _totals(*, planned="0.00", paid="0.00", unpaid="0.00", overdue="0.00", forecast="0.00"):
    return dict(planned=planned, paid=paid, unpaid=unpaid, overdue=overdue, forecast=forecast)


def _today(monkeypatch, value=date(2026, 10, 24)):
    monkeypatch.setattr(budget, "today_in_timezone", lambda _timezone: value)


async def _seed_rule(
    app,
    *,
    first=date(2026, 10, 31),
    amount="10.00",
    currency="RUB",
    active=True,
    periods=(),
):
    async with app.state.database.session_factory() as db:
        rule = RecurringPayment(
            id=uuid4(),
            title="Budget rule",
            amount=Decimal(amount),
            currency=currency,
            first_due_date=first,
            periodicity="monthly",
            anchor_day=first.day,
            is_active=active,
        )
        db.add(rule)
        await db.flush()
        occurrences = [
            PaymentOccurrence(
                id=uuid4(),
                recurring_payment_id=rule.id,
                due_date=due_date,
                status=status,
                paid_on=paid_on,
            )
            for due_date, status, paid_on in periods
        ]
        db.add_all(occurrences)
        await db.commit()
        return rule, occurrences


async def _counts(app):
    async with app.state.database.session_factory() as db:
        return (
            await db.scalar(select(func.count()).select_from(PaymentOccurrence)),
            await db.scalar(select(func.count()).select_from(deliveries)),
        )


@pytest.mark.parametrize("role", ["admin", "user"])
async def test_budget_requires_auth_and_empty_year_has_every_month(
    app, client, create_user, login, monkeypatch, role
):
    _today(monkeypatch)
    denied = await client.get(PATH, params={"year": 2026})
    assert_error(denied, 401, "AUTH_REQUIRED")
    await create_user("budget_reader", role=role)
    await login(client, "budget_reader")
    response = await client.get(PATH, params={"year": 2026})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["year"] == 2026 and data["month"] is None
    assert data["date_from"] == "2026-01-01" and data["date_to"] == "2026-12-31"
    assert data["as_of_date"] == "2026-10-24"
    assert data["timezone"] == app.state.settings.app_timezone
    assert data["totals"] == {currency: _totals() for currency in CURRENCIES}
    assert data["months"] == [{"month": month, "totals": data["totals"]} for month in range(1, 13)]
    assert response.headers["cache-control"] == "no-store"


async def test_budget_actual_states_forecast_currencies_and_month_year_totals(
    app, client, create_user, login, monkeypatch
):
    _today(monkeypatch)
    await create_user()
    await login(client)
    for values in [
        dict(
            first=date(2026, 10, 1),
            amount="100.00",
            periods=[(date(2026, 10, 1), "paid", date(2026, 10, 2))],
        ),
        dict(
            first=date(2026, 10, 10),
            amount="0.01",
            periods=[(date(2026, 10, 10), "unpaid", None)],
        ),
        dict(
            first=date(2026, 10, 31),
            amount="20.00",
            periods=[(date(2026, 10, 31), "unpaid", None)],
        ),
        dict(
            first=date(2026, 10, 31),
            amount="999999999999.99",
            currency="USD",
            periods=[(date(2026, 10, 31), "paid", date(2026, 10, 24))],
        ),
        dict(
            first=date(2026, 10, 24),
            amount="1.23",
            currency="EUR",
            periods=[(date(2026, 10, 24), "unpaid", None)],
        ),
    ]:
        await _seed_rule(app, **values)

    before = await _counts(app)
    annual = await client.get(PATH, params={"year": 2026})
    assert annual.status_code == 200, annual.text
    data = annual.json()
    assert data["months"][9]["totals"]["RUB"] == _totals(
        planned="120.01", paid="100.00", unpaid="20.01", overdue="0.01"
    )
    assert data["totals"]["RUB"] == _totals(
        planned="360.03", paid="100.00", unpaid="20.01", overdue="0.01", forecast="240.02"
    )
    assert data["totals"]["USD"] == _totals(
        planned="2999999999999.97", paid="999999999999.99", forecast="1999999999999.98"
    )
    assert data["totals"]["EUR"] == _totals(planned="3.69", unpaid="1.23", forecast="2.46")
    for month in data["months"]:
        selected = await client.get(PATH, params={"year": 2026, "month": month["month"]})
        assert selected.status_code == 200, selected.text
        assert selected.json()["months"] == [month]
        assert selected.json()["totals"] == month["totals"]
        assert selected.json()["month"] == month["month"]
    for currency in CURRENCIES:
        for field in FIELDS:
            assert Decimal(data["totals"][currency][field]) == sum(
                Decimal(month["totals"][currency][field]) for month in data["months"]
            )
    assert await _counts(app) == before


async def test_budget_assigns_late_payment_by_due_date_and_tracks_reverted_payment(
    app, client, create_user, login, monkeypatch
):
    _today(monkeypatch)
    await create_user()
    auth = await login(client)
    _, periods = await _seed_rule(
        app,
        first=date(2026, 9, 30),
        periods=[
            (date(2026, 9, 30), "paid", date(2026, 10, 3)),
            (date(2026, 10, 30), "unpaid", None),
        ],
    )
    september = await client.get(PATH, params={"year": 2026, "month": 9})
    assert september.status_code == 200, september.text
    assert september.json()["totals"]["RUB"] == _totals(planned="10.00", paid="10.00")
    october = await client.get(PATH, params={"year": 2026, "month": 10})
    assert october.status_code == 200, october.text
    assert october.json()["totals"]["RUB"] == _totals(planned="10.00", unpaid="10.00")
    reverted = await client.patch(
        f"/api/v1/payment-occurrences/{periods[0].id}",
        json={"status": "unpaid", "paid_on": None},
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert reverted.status_code == 200, reverted.text
    september = await client.get(PATH, params={"year": 2026, "month": 9})
    assert september.json()["totals"]["RUB"] == _totals(
        planned="10.00", unpaid="10.00", overdue="10.00"
    )


@pytest.mark.parametrize(
    ("first", "year", "forecast"),
    [
        (date(2027, 1, 31), 2027, "120.00"),
        (date(2027, 1, 30), 2028, "120.00"),
        (date(2028, 2, 29), 2028, "110.00"),
        (date(2027, 12, 31), 2027, "10.00"),
        (date(2028, 1, 31), 2027, "0.00"),
    ],
)
async def test_budget_projects_original_anchor_and_first_date_without_writing(
    app, client, create_user, login, monkeypatch, first, year, forecast
):
    _today(monkeypatch)
    await create_user()
    await login(client)
    await _seed_rule(app, first=first)
    before = await _counts(app)
    assert before == (0, 0)
    for _ in range(2):
        response = await client.get(PATH, params={"year": year})
        assert response.status_code == 200, response.text
        assert response.json()["totals"]["RUB"] == _totals(planned=forecast, forecast=forecast)
    assert await _counts(app) == before


async def test_budget_persisted_future_anchor_is_not_counted_twice(
    app, client, create_user, login, monkeypatch
):
    _today(monkeypatch)
    await create_user()
    await login(client)
    await _seed_rule(
        app,
        first=date(2027, 1, 31),
        periods=[(date(2027, 2, 28), "unpaid", None)],
    )
    response = await client.get(PATH, params={"year": 2027})
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["RUB"] == _totals(
        planned="120.00", unpaid="10.00", forecast="110.00"
    )
    assert response.json()["months"][1]["totals"]["RUB"] == _totals(planned="10.00", unpaid="10.00")


async def test_budget_stopped_rule_keeps_obligations_and_has_no_forecast(
    app, client, create_user, login, monkeypatch
):
    _today(monkeypatch)
    await create_user()
    await login(client)
    await _seed_rule(
        app,
        first=date(2027, 1, 31),
        active=False,
        periods=[(date(2027, 1, 31), "unpaid", None)],
    )
    await _seed_rule(app, first=date(2027, 1, 1), amount="50.00", active=False)
    response = await client.get(PATH, params={"year": 2027})
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["RUB"] == _totals(planned="10.00", unpaid="10.00")
    assert all(item["totals"]["RUB"] == _totals() for item in response.json()["months"][1:])


@pytest.mark.parametrize("first", [date(2026, 9, 30), date(2026, 10, 31)])
async def test_budget_refuses_missing_history_including_remaining_current_month(
    app, client, create_user, login, monkeypatch, first
):
    _today(monkeypatch)
    await create_user()
    await login(client)
    await _seed_rule(app, first=first)
    before = await _counts(app)
    response = await client.get(PATH, params={"year": 2026})
    assert_error(response, 503, "PERIODS_NOT_READY")
    assert await _counts(app) == before
    future = await client.get(PATH, params={"year": 2027})
    assert future.status_code == 200, future.text
    assert future.json()["totals"]["RUB"] == _totals(planned="120.00", forecast="120.00")


@pytest.mark.parametrize("year", [1, 9999])
async def test_budget_extreme_years_do_not_overflow(
    app, client, create_user, login, monkeypatch, year
):
    _today(monkeypatch)
    await create_user()
    await login(client)
    await _seed_rule(app, first=date(2027, 1, 31))
    response = await client.get(PATH, params={"year": year})
    assert response.status_code == 200, response.text
    assert response.json()["date_from"] == f"{year:04d}-01-01"
    assert response.json()["date_to"] == f"{year:04d}-12-31"
    expected = "0.00" if year == 1 else "120.00"
    assert response.json()["totals"]["RUB"] == _totals(planned=expected, forecast=expected)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"month": 10},
        {"year": 0},
        {"year": 10000},
        {"year": "2026.5"},
        {"year": "invalid"},
        {"year": 2026, "month": 0},
        {"year": 2026, "month": 13},
        {"year": 2026, "date_from": "2026-01-01"},
    ],
)
async def test_budget_rejects_missing_invalid_and_unknown_parameters(
    client, create_user, login, params
):
    await create_user()
    await login(client)
    response = await client.get(PATH, params=params)
    assert_error(response, 422, "VALIDATION_ERROR")
    assert response.json()["error"]["details"]
    assert all(
        set(detail) == {"field", "code", "message"}
        for detail in response.json()["error"]["details"]
    )


async def test_budget_gets_as_of_date_in_configured_timezone(
    app, client, create_user, login, monkeypatch
):
    await create_user()
    await login(client)
    seen = []

    def today(timezone_name):
        seen.append(timezone_name)
        return date(2026, 12, 31)

    monkeypatch.setattr(budget, "today_in_timezone", today)
    app.state.settings.app_timezone = "Asia/Tokyo"
    response = await client.get(PATH, params={"year": 2026, "month": 12})
    assert response.status_code == 200, response.text
    assert seen == ["Asia/Tokyo"]
    assert response.json()["as_of_date"] == "2026-12-31"
    assert response.json()["timezone"] == "Asia/Tokyo"
