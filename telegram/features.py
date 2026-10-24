"""Telegram presentation helpers; business dates and statuses come from the API."""

import html

from formatting import format_amount, format_date


def escaped(value):
    return html.escape(str(value), quote=False)


def payment_status(payment, texts):
    if payment["status"] == "paid":
        status = "paid_late" if payment["paid_late"] else "paid"
    elif payment["status"] == "unpaid":
        status = "overdue" if payment["is_overdue"] else "unpaid"
    else:
        raise ValueError("Unknown payment status")
    label = texts["PAYMENT_STATUSES"][status]
    if payment["days_late"] and status in {"overdue", "paid_late"}:
        label += texts["DAYS_LATE"].format(days=payment["days_late"])
    return label


def payment_list_item(payment, texts, index):
    return texts["PAYMENT_LIST_ITEM"].format(
        number=index,
        title=escaped(payment["title"]),
        amount=escaped(format_amount(payment["amount"], payment["currency"])),
        due_date=escaped(format_date(payment["due_date"])),
        status=escaped(payment_status(payment, texts)),
    )


def payment_card(payment, texts, index=None):
    title = str(payment["title"])
    if index is not None:
        title = f"{index}. {title}"
    result = texts["PAYMENT_CARD"].format(
        title=escaped(title),
        amount=escaped(format_amount(payment["amount"], payment["currency"])),
        due_date=escaped(format_date(payment["due_date"])),
        status=escaped(payment_status(payment, texts)),
    )
    if payment["paid_on"] is not None:
        result += texts["PAYMENT_CARD_PAID_ON"].format(
            paid_on=escaped(format_date(payment["paid_on"]))
        )
    if not payment["recurring_payment_is_active"]:
        result += texts["PAYMENT_STOPPED"]
    return result


def summary_text(summary, texts):
    header = texts["SUMMARY_TITLE"].format(
        date_from=escaped(format_date(summary["date_from"])),
        date_to=escaped(format_date(summary["date_to"])),
        as_of_date=escaped(format_date(summary["as_of_date"])),
        timezone=escaped(summary["timezone"]),
    )
    rows = [
        texts["SUMMARY_CURRENCY"].format(
            currency=escaped(currency),
            **{
                name: escaped(format_amount(summary["totals"][currency][name], currency))
                for name in ("planned", "paid", "unpaid", "overdue")
            },
        )
        for currency in ("RUB", "USD", "EUR")
    ]
    return header + "\n\n" + "\n\n".join(rows)
