from calendar import monthrange
from datetime import date


def due_date_in_month(anchor_day: int, year: int, month: int) -> date:
    return date(year, month, min(anchor_day, monthrange(year, month)[1]))


def next_due_date(
    first_due_date: date,
    anchor_day: int,
    today: date,
    periodicity: str = "monthly",
    interval: int = 1,
) -> date | None:
    if today <= first_due_date:
        return first_due_date
    if periodicity == "once":
        return None
    if periodicity in ("daily", "weekly"):
        step = interval * (7 if periodicity == "weekly" else 1)
        elapsed = (today - first_due_date).days
        ordinal = first_due_date.toordinal() + ((elapsed + step - 1) // step) * step
        return date.fromordinal(ordinal) if ordinal <= date.max.toordinal() else None
    step = interval * (12 if periodicity == "yearly" else 1)
    first_month = (first_due_date.year - 1) * 12 + first_due_date.month - 1
    elapsed = (today.year - first_due_date.year) * 12 + today.month - first_due_date.month
    month_index = first_month + (elapsed // step) * step
    year, month = divmod(month_index, 12)
    candidate = due_date_in_month(anchor_day, year + 1, month + 1)
    if candidate < today:
        year, month = divmod(month_index + step, 12)
        return due_date_in_month(anchor_day, year + 1, month + 1) if year < 9999 else None
    return candidate


def monthly_due_dates(first_due_date: date, anchor_day: int, through: date) -> list[date]:
    return recurring_due_dates(first_due_date, anchor_day, through)


def recurring_due_dates(
    first_due_date: date,
    anchor_day: int,
    through: date,
    periodicity: str = "monthly",
    interval: int = 1,
    *,
    start: date | None = None,
) -> list[date]:
    result = []
    due = next_due_date(first_due_date, anchor_day, start or first_due_date, periodicity, interval)
    while due is not None and due <= through:
        result.append(due)
        if due == date.max:
            break
        due = next_due_date(
            first_due_date,
            anchor_day,
            date.fromordinal(due.toordinal() + 1),
            periodicity,
            interval,
        )
    return result
