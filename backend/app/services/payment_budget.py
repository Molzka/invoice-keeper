from calendar import monthrange
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaymentOccurrence, RecurringPayment
from app.services.errors import api_error
from app.services.payment_calendar import due_date_in_month

CURRENCIES = ("RUB", "USD", "EUR")
FIELDS = ("planned", "paid", "unpaid", "overdue", "forecast")
ZERO = Decimal("0.00")


def _empty_totals() -> dict[str, dict[str, Decimal]]:
    return {currency: {field: ZERO for field in FIELDS} for currency in CURRENCIES}


def _money_totals(totals: dict[str, dict[str, Decimal]]) -> dict:
    return {
        currency: {field: format(amount, ".2f") for field, amount in values.items()}
        for currency, values in totals.items()
    }


async def get_payments_budget(
    db: AsyncSession,
    *,
    today: date,
    year: int,
    month: int | None,
    timezone_name: str,
) -> dict:
    """Combine persisted obligations with a projection without generating periods/jobs."""
    months = [month] if month is not None else list(range(1, 13))
    date_from = date(year, months[0], 1)
    last_month = months[-1]
    date_to = date(year, last_month, monthrange(year, last_month)[1])
    current_month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    complete_through = min(date_to, current_month_end)

    # One SQL statement sees rules and their periods in the same PostgreSQL snapshot.
    # Include stopped rules only when they have a real obligation in the selected range.
    rows = await db.execute(
        select(RecurringPayment, PaymentOccurrence)
        .outerjoin(
            PaymentOccurrence,
            and_(
                PaymentOccurrence.recurring_payment_id == RecurringPayment.id,
                PaymentOccurrence.due_date.between(date_from, date_to),
            ),
        )
        .where(or_(RecurringPayment.is_active.is_(True), PaymentOccurrence.id.is_not(None)))
    )
    rules: dict[UUID, RecurringPayment] = {}
    existing_dates: dict[UUID, set[date]] = {}
    monthly = {number: _empty_totals() for number in months}
    for rule, occurrence in rows:
        rules[rule.id] = rule
        existing_dates.setdefault(rule.id, set())
        if occurrence is None:
            continue
        existing_dates[rule.id].add(occurrence.due_date)
        totals = monthly[occurrence.due_date.month][rule.currency]
        totals["planned"] += rule.amount
        totals[occurrence.status] += rule.amount
        if occurrence.status == "unpaid" and occurrence.due_date < today:
            totals["overdue"] += rule.amount

    for rule in rules.values():
        if not rule.is_active:
            continue
        for number in months:
            due_date = due_date_in_month(rule.anchor_day, year, number)
            if due_date < rule.first_due_date or due_date in existing_dates[rule.id]:
                continue
            if due_date <= complete_through:
                raise api_error(
                    503,
                    "PERIODS_NOT_READY",
                    "История периодов ещё восстанавливается",
                )
            totals = monthly[number][rule.currency]
            totals["planned"] += rule.amount
            totals["forecast"] += rule.amount

    totals = _empty_totals()
    for values in monthly.values():
        for currency in CURRENCIES:
            for field in FIELDS:
                totals[currency][field] += values[currency][field]
    return {
        "year": year,
        "month": month,
        "date_from": date_from,
        "date_to": date_to,
        "as_of_date": today,
        "timezone": timezone_name,
        "totals": _money_totals(totals),
        "months": [
            {"month": number, "totals": _money_totals(monthly[number])} for number in months
        ],
    }
