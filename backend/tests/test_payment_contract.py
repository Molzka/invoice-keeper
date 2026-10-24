from datetime import date

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.payments import PaymentStateUpdate, RecurringPaymentCreate
from app.services.payment_calendar import due_date_in_month, monthly_due_dates, next_due_date


@pytest.mark.parametrize(
    ("anchor", "year", "month", "expected"),
    [
        (31, 2027, 2, date(2027, 2, 28)),
        (31, 2028, 2, date(2028, 2, 29)),
        (30, 2027, 2, date(2027, 2, 28)),
        (30, 2027, 3, date(2027, 3, 30)),
        (28, 2028, 2, date(2028, 2, 28)),
        (31, 2027, 12, date(2027, 12, 31)),
    ],
)
def test_due_date_uses_original_anchor(anchor, year, month, expected):
    assert due_date_in_month(anchor, year, month) == expected


@pytest.mark.parametrize(
    ("first", "today", "expected"),
    [
        (date(2027, 1, 31), date(2027, 2, 27), date(2027, 2, 28)),
        (date(2027, 1, 31), date(2027, 2, 28), date(2027, 2, 28)),
        (date(2027, 1, 31), date(2027, 3, 1), date(2027, 3, 31)),
        (date(2027, 1, 31), date(2027, 3, 30), date(2027, 3, 31)),
        (date(2027, 12, 31), date(2027, 11, 1), date(2027, 12, 31)),
    ],
)
def test_next_due_date_is_the_nearest_unexpired_anchor_date(first, today, expected):
    assert next_due_date(first, first.day, today) == expected


def test_monthly_due_dates_keep_anchor_across_february_and_year_boundary():
    assert monthly_due_dates(date(2027, 1, 31), 31, date(2027, 3, 31)) == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
    ]
    assert monthly_due_dates(date(2027, 12, 31), 31, date(2028, 2, 29)) == [
        date(2027, 12, 31),
        date(2028, 1, 31),
        date(2028, 2, 29),
    ]


@pytest.mark.parametrize("amount", ["0.01", "999999999999.99", "0000000000001.00"])
@pytest.mark.parametrize("currency", ["RUB", "USD", "EUR"])
def test_recurring_payment_accepts_exact_money_strings(amount, currency):
    payment = RecurringPaymentCreate(
        title="  Office  ",
        amount=amount,
        currency=currency,
        first_due_date="2026-10-31",
        periodicity="monthly",
    )
    assert payment.title == "Office"
    assert payment.amount == amount


@pytest.mark.parametrize(
    "amount",
    [
        0.01,
        True,
        "0",
        "0.00",
        "-1.00",
        "+1.00",
        "1,00",
        "1.0",
        "1.000",
        "1e2",
        "1.00 ",
        "1000000000000.00",
    ],
)
def test_recurring_payment_rejects_invalid_money(amount):
    with pytest.raises(ValidationError):
        RecurringPaymentCreate(
            title="Office",
            amount=amount,
            currency="RUB",
            first_due_date="2026-10-31",
            periodicity="monthly",
        )


@pytest.mark.parametrize(
    "state",
    [
        {"status": "paid", "paid_on": "2026-10-23"},
        {"status": "unpaid", "paid_on": None},
    ],
)
def test_payment_state_accepts_only_consistent_forms(state):
    actual = PaymentStateUpdate(**state)
    assert actual.status == state["status"]
    assert actual.paid_on == (
        date.fromisoformat(state["paid_on"]) if state["paid_on"] is not None else None
    )


@pytest.mark.parametrize(
    "state",
    [
        {"status": "paid", "paid_on": None},
        {"status": "unpaid", "paid_on": "2026-10-23"},
        {"status": "pending", "paid_on": None},
        {"status": "unpaid"},
        {"status": "unpaid", "paid_on": None, "amount": "10.00"},
    ],
)
def test_payment_state_rejects_inconsistent_or_unknown_fields(state):
    with pytest.raises(ValidationError):
        PaymentStateUpdate(**state)


def test_payment_openapi_documents_contract_and_empty_pages():
    schema = create_app(Settings(_env_file=None, database_url=None)).openapi()
    paths = schema["paths"]
    assert set(paths["/api/v1/recurring-payments"]) == {"get", "post"}
    assert "delete" in paths["/api/v1/recurring-payments/{payment_id}"]
    assert "patch" in paths["/api/v1/payment-occurrences/{occurrence_id}"]
    assert "get" in paths["/api/v1/payments/summary"]
    assert schema["components"]["securitySchemes"]["SessionCookie"]["name"] == "session_id"

    create_operation = paths["/api/v1/recurring-payments"]["post"]
    assert "SessionCookie" in create_operation["security"][0]
    assert create_operation["responses"]["201"]["content"]["application/json"]
    assert (
        "content"
        not in paths["/api/v1/recurring-payments/{payment_id}"]["delete"]["responses"]["204"]
    )
    assert "X-CSRF-Token" in {parameter["name"] for parameter in create_operation["parameters"]}

    amount = schema["components"]["schemas"]["RecurringPaymentCreate"]["properties"]["amount"]
    assert amount["type"] == "string"
    assert amount["pattern"] == r"^[0-9]+\.[0-9]{2}$"
    assert set(schema["components"]["schemas"]["PaymentStateUpdate"]["required"]) == {
        "status",
        "paid_on",
    }
    assert any(
        not example["items"]
        for example in schema["components"]["schemas"]["RecurringPaymentList"]["examples"]
    )
    assert "503" in paths["/api/v1/payments/summary"]["get"]["responses"]
