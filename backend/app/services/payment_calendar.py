from calendar import monthrange
from datetime import date


def due_date_in_month(anchor_day: int, year: int, month: int) -> date:
    return date(year, month, min(anchor_day, monthrange(year, month)[1]))


def next_due_date(first_due_date: date, anchor_day: int, today: date) -> date:
    month_index = max(
        first_due_date.year * 12 + first_due_date.month - 1,
        today.year * 12 + today.month - 1,
    )
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    candidate = due_date_in_month(anchor_day, year, month)
    if candidate < first_due_date or candidate < today:
        month_index += 1
        year, month_zero_based = divmod(month_index, 12)
        candidate = due_date_in_month(anchor_day, year, month_zero_based + 1)
    return candidate


def monthly_due_dates(first_due_date: date, anchor_day: int, through: date) -> list[date]:
    if through < first_due_date:
        return []
    first_month = first_due_date.year * 12 + first_due_date.month - 1
    last_month = through.year * 12 + through.month - 1
    result = []
    for month_index in range(first_month, last_month + 1):
        year, month_zero_based = divmod(month_index, 12)
        due_date = due_date_in_month(anchor_day, year, month_zero_based + 1)
        if first_due_date <= due_date <= through:
            result.append(due_date)
    return result
