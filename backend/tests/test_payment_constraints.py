from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import PaymentOccurrence, RecurringPayment

pytestmark = pytest.mark.asyncio


def _rule(**changes):
    values = {
        "title": "Office",
        "amount": Decimal("10.00"),
        "currency": "RUB",
        "first_due_date": date(2026, 10, 31),
        "periodicity": "monthly",
        "anchor_day": 31,
    }
    values.update(changes)
    return RecurringPayment(**values)


async def _assert_rejected(db, model):
    db.add(model)
    with pytest.raises(DBAPIError) as rejected:
        await db.commit()
    assert rejected.value.orig.sqlstate in {"23502", "23503", "23505", "23514", "22003"}
    await db.rollback()


async def test_payment_database_constraints_reject_invalid_rules_and_states(app):
    async with app.state.database.session_factory() as db:
        rule = _rule()
        db.add(rule)
        await db.flush()
        rule_id = rule.id
        await db.commit()

        for invalid_rule in (
            _rule(title="   "),
            _rule(title="\t\n"),
            _rule(amount=Decimal("0.00")),
            _rule(currency="CAD"),
            _rule(periodicity="weekly"),
            _rule(anchor_day=28),
        ):
            await _assert_rejected(db, invalid_rule)

        await _assert_rejected(
            db,
            PaymentOccurrence(
                recurring_payment_id=rule_id,
                amount=Decimal("10.00"),
                currency="RUB",
                due_date=date(2026, 10, 31),
                status="paid",
                paid_on=None,
            ),
        )
        await _assert_rejected(
            db,
            PaymentOccurrence(
                recurring_payment_id=rule_id,
                amount=Decimal("10.00"),
                currency="RUB",
                due_date=date(2026, 11, 30),
                status="unpaid",
                paid_on=date(2026, 11, 30),
            ),
        )
        await _assert_rejected(
            db,
            PaymentOccurrence(
                recurring_payment_id=rule_id,
                amount=Decimal("10.00"),
                currency="RUB",
                due_date=date(2026, 12, 31),
                status="pending",
            ),
        )

        valid = PaymentOccurrence(
            recurring_payment_id=rule_id,
            amount=Decimal("10.00"),
            currency="RUB",
            due_date=date(2026, 10, 31),
        )
        db.add(valid)
        await db.commit()
        await _assert_rejected(
            db,
            PaymentOccurrence(
                recurring_payment_id=rule_id,
                amount=Decimal("10.00"),
                currency="RUB",
                due_date=date(2026, 10, 31),
            ),
        )
        await _assert_rejected(
            db,
            PaymentOccurrence(
                recurring_payment_id=uuid4(),
                amount=Decimal("10.00"),
                currency="RUB",
                due_date=date(2026, 12, 31),
            ),
        )

        rule = await db.get(RecurringPayment, rule_id)
        await db.delete(rule)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_payment_snapshot_database_constraints_reject_invalid_money_and_currency(app):
    async with app.state.database.session_factory() as db:
        rule = _rule()
        db.add(rule)
        await db.flush()
        identity = rule.id
        await db.commit()
        for amount, currency in (
            (None, "RUB"),
            (Decimal("0.00"), "RUB"),
            (Decimal("-1.00"), "RUB"),
            (Decimal("1000000000000.00"), "RUB"),
            (Decimal("10.00"), None),
            (Decimal("10.00"), "CAD"),
        ):
            await _assert_rejected(
                db,
                PaymentOccurrence(
                    recurring_payment_id=identity,
                    due_date=date(2026, 10, 31),
                    amount=amount,
                    currency=currency,
                ),
            )
        valid = PaymentOccurrence(
            recurring_payment_id=identity,
            due_date=date(2026, 10, 31),
            amount=Decimal("999999999999.99"),
            currency="EUR",
        )
        db.add(valid)
        await db.commit()
        await db.refresh(valid)
        assert valid.amount == Decimal("999999999999.99")
        assert valid.amount_is_custom is False
