from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_amount(amount, currency) -> str:
    raw = str(amount).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"Некорректная сумма: {amount!r}")
    value = value.quantize(Decimal("0.01"), ROUND_HALF_UP)
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} {currency}"


def format_date(value) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass
    raise ValueError(f"Некорректная дата: {value!r}")