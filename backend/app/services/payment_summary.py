from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.locking import lock_payments
from app.models import PaymentOccurrence, RecurringPayment
from app.services.errors import api_error
from app.services.payment_calendar import monthly_due_dates

CURRENCIES = ("RUB", "USD", "EUR")
ZERO = Decimal("0.00")


def _date_range(date_from: date | None, date_to: date | None, today: date) -> tuple[date, date]:
    if (date_from is None) != (date_to is None):
        raise api_error(422, "VALIDATION_ERROR", "Укажите обе границы диапазона")
    if date_from is None:
        return date(today.year, today.month, 1), date(
            today.year, today.month, monthrange(today.year, today.month)[1]
        )
    if date_from > date_to:
        raise api_error(422, "VALIDATION_ERROR", "Начало диапазона позже его окончания")
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    if date_to > month_end:
        raise api_error(422, "VALIDATION_ERROR", "Конец диапазона позже текущего месяца")
    return date_from, date_to


async def _assert_active_history_complete(
    db: AsyncSession,
    rules: list[RecurringPayment],
    date_to: date,
) -> None:
    expected: dict[UUID, set[date]] = {
        rule.id: ({rule.first_due_date} if rule.first_due_date <= date_to else set())
        if rule.periodicity == "once"
        else set(monthly_due_dates(rule.first_due_date, rule.anchor_day, date_to))
        for rule in rules
    }
    expected = {payment_id: dates for payment_id, dates in expected.items() if dates}
    if not expected:
        return
    actual_rows = await db.execute(
        select(PaymentOccurrence.recurring_payment_id, PaymentOccurrence.due_date).where(
            PaymentOccurrence.recurring_payment_id.in_(expected),
            PaymentOccurrence.due_date <= date_to,
        )
    )
    actual: dict[UUID, set[date]] = defaultdict(set)
    for payment_id, due_date in actual_rows:
        actual[payment_id].add(due_date)
    if any(dates - actual.get(payment_id, set()) for payment_id, dates in expected.items()):
        raise api_error(
            503,
            "PERIODS_NOT_READY",
            "История периодов ещё восстанавливается",
        )


async def get_payments_summary(
    db: AsyncSession,
    today: date,
    date_from: date | None,
    date_to: date | None,
    timezone_name: str,
) -> dict:
    date_from, date_to = _date_range(date_from, date_to, today)
    await lock_payments(db)
    active_rules = list(
        await db.scalars(
            select(RecurringPayment)
            .where(RecurringPayment.is_active.is_(True))
            .order_by(RecurringPayment.id)
            .with_for_update()
        )
    )
    await _assert_active_history_complete(db, active_rules, date_to)

    overdue = and_(PaymentOccurrence.status == "unpaid", PaymentOccurrence.due_date < today)
    result = await db.execute(
        select(
            PaymentOccurrence.currency,
            func.sum(PaymentOccurrence.amount),
            func.sum(case((PaymentOccurrence.status == "paid", PaymentOccurrence.amount), else_=0)),
            func.sum(
                case((PaymentOccurrence.status == "unpaid", PaymentOccurrence.amount), else_=0)
            ),
            func.sum(case((overdue, PaymentOccurrence.amount), else_=0)),
        )
        .select_from(PaymentOccurrence)
        .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
        .where(
            PaymentOccurrence.due_date.between(date_from, date_to),
            PaymentOccurrence.is_cancelled.is_(False),
        )
        .group_by(PaymentOccurrence.currency)
    )
    totals = {
        currency: {
            key: format(amount or ZERO, ".2f")
            for key, amount in zip(("planned", "paid", "unpaid", "overdue"), values)
        }
        for currency, *values in result
    }
    response = {
        "date_from": date_from,
        "date_to": date_to,
        "as_of_date": today,
        "timezone": timezone_name,
        "totals": {
            currency: totals.get(
                currency,
                {key: "0.00" for key in ("planned", "paid", "unpaid", "overdue")},
            )
            for currency in CURRENCIES
        },
    }
    await db.commit()
    return response
