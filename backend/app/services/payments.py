from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.locking import lock_payments
from app.models import PaymentOccurrence, RecurringPayment, User
from app.schemas.payments import PaymentStateUpdate, RecurringPaymentCreate
from app.services.audit import record_audit_event
from app.services.errors import api_error
from app.services.payment_calendar import next_due_date
from app.services.payment_periods import (
    ensure_payment_periods,
)


def today_in_timezone(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def money_string(amount: Decimal) -> str:
    return format(amount, ".2f")


def recurring_payment_data(
    payment: RecurringPayment,
    today: date,
) -> dict:
    return {
        "id": payment.id,
        "title": payment.title,
        "amount": money_string(payment.amount),
        "currency": payment.currency,
        "first_due_date": payment.first_due_date,
        "next_due_date": (
            next_due_date(payment.first_due_date, payment.anchor_day, today)
            if payment.is_active
            else None
        ),
        "periodicity": payment.periodicity,
        "anchor_day": payment.anchor_day,
        "is_active": payment.is_active,
        "created_at": payment.created_at,
    }


def occurrence_data(
    payment: RecurringPayment,
    occurrence: PaymentOccurrence,
    today: date,
) -> dict:
    paid = occurrence.status == "paid"
    reference_date = occurrence.paid_on if paid else today
    days_late = max(0, (reference_date - occurrence.due_date).days)
    return {
        "id": occurrence.id,
        "recurring_payment_id": payment.id,
        "title": payment.title,
        "amount": money_string(payment.amount),
        "currency": payment.currency,
        "due_date": occurrence.due_date,
        "status": occurrence.status,
        "paid_on": occurrence.paid_on,
        "is_overdue": not paid and today > occurrence.due_date,
        "paid_late": paid and occurrence.paid_on > occurrence.due_date,
        "days_late": days_late,
        "recurring_payment_is_active": payment.is_active,
    }


async def create_recurring_payment(
    db: AsyncSession,
    payload: RecurringPaymentCreate,
    today: date,
    *,
    actor: User | None = None,
) -> RecurringPayment:
    await lock_payments(db)
    payment = RecurringPayment(
        title=payload.title,
        amount=Decimal(payload.amount),
        currency=payload.currency,
        first_due_date=payload.first_due_date,
        periodicity=payload.periodicity,
        anchor_day=payload.first_due_date.day,
    )
    db.add(payment)
    await db.flush()
    await ensure_payment_periods(db, payment.id, today)
    if actor is not None:
        record_audit_event(
            db,
            actor=actor,
            action="payment.created",
            entity_type="payment",
            entity_id=payment.id,
            entity_title=payment.title,
            changes=[
                {"field": "title", "label": "Название", "before": None, "after": payment.title},
                {
                    "field": "amount",
                    "label": "Сумма",
                    "before": None,
                    "after": money_string(payment.amount),
                },
                {
                    "field": "currency",
                    "label": "Валюта",
                    "before": None,
                    "after": payment.currency,
                },
                {
                    "field": "first_due_date",
                    "label": "Первый срок",
                    "before": None,
                    "after": payment.first_due_date.isoformat(),
                },
            ],
        )
    await db.commit()
    return payment


async def list_recurring_payments(
    db: AsyncSession,
    today: date,
    *,
    limit: int,
    offset: int,
    is_active: bool | None,
) -> tuple[list[dict], int]:
    filters = [] if is_active is None else [RecurringPayment.is_active.is_(is_active)]
    total = await db.scalar(select(func.count()).select_from(RecurringPayment).where(*filters))
    result = await db.scalars(
        select(RecurringPayment)
        .where(*filters)
        .order_by(RecurringPayment.created_at.desc(), RecurringPayment.id)
        .limit(limit)
        .offset(offset)
    )
    return [recurring_payment_data(item, today) for item in result], total or 0


async def stop_recurring_payment(
    db: AsyncSession,
    payment_id: UUID,
    today: date,
    *,
    actor: User | None = None,
) -> None:
    payment = await ensure_payment_periods(db, payment_id, today, through=today)
    if payment is None:
        raise api_error(404, "RECURRING_PAYMENT_NOT_FOUND", "Регулярный платёж не найден")
    if payment.is_active:
        payment.is_active = False
        if actor is not None:
            record_audit_event(
                db,
                actor=actor,
                action="payment.stopped",
                entity_type="payment",
                entity_id=payment.id,
                entity_title=payment.title,
                changes=[
                    {
                        "field": "is_active",
                        "label": "Регулярный платёж",
                        "before": "Действует",
                        "after": "Прекращён",
                    }
                ],
            )
    await db.commit()


async def list_payment_occurrences(
    db: AsyncSession,
    today: date,
    *,
    date_from: date | None,
    date_to: date | None,
    status: str | None,
    currency: str | None,
    recurring_payment_id: UUID | None,
    is_overdue: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise api_error(422, "VALIDATION_ERROR", "Начало диапазона позже его окончания")
    filters = []
    if date_from is not None:
        filters.append(PaymentOccurrence.due_date >= date_from)
    if date_to is not None:
        filters.append(PaymentOccurrence.due_date <= date_to)
    if status is not None:
        filters.append(PaymentOccurrence.status == status)
    if currency is not None:
        filters.append(RecurringPayment.currency == currency)
    if recurring_payment_id is not None:
        filters.append(PaymentOccurrence.recurring_payment_id == recurring_payment_id)
    if is_overdue is True:
        filters.extend([PaymentOccurrence.status == "unpaid", PaymentOccurrence.due_date < today])
    elif is_overdue is False:
        filters.append(
            or_(
                PaymentOccurrence.status == "paid",
                PaymentOccurrence.due_date >= today,
            )
        )

    total = await db.scalar(
        select(func.count(PaymentOccurrence.id))
        .join(RecurringPayment, PaymentOccurrence.recurring_payment_id == RecurringPayment.id)
        .where(*filters)
    )
    result = await db.execute(
        select(PaymentOccurrence, RecurringPayment)
        .join(RecurringPayment, PaymentOccurrence.recurring_payment_id == RecurringPayment.id)
        .where(*filters)
        .order_by(PaymentOccurrence.due_date, PaymentOccurrence.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        occurrence_data(payment, occurrence, today) for occurrence, payment in result
    ], total or 0


async def get_payment_occurrence(
    db: AsyncSession,
    occurrence_id: UUID,
    today: date,
) -> dict:
    row = await db.execute(
        select(PaymentOccurrence, RecurringPayment)
        .join(RecurringPayment, PaymentOccurrence.recurring_payment_id == RecurringPayment.id)
        .where(PaymentOccurrence.id == occurrence_id)
    )
    result = row.one_or_none()
    if result is None:
        raise api_error(404, "PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")
    occurrence, payment = result
    return occurrence_data(payment, occurrence, today)


async def update_payment_state(
    db: AsyncSession,
    occurrence_id: UUID,
    payload: PaymentStateUpdate,
    today: date,
    *,
    actor: User | None = None,
) -> dict:
    await lock_payments(db)
    payment_id = await db.scalar(
        select(PaymentOccurrence.recurring_payment_id).where(PaymentOccurrence.id == occurrence_id)
    )
    if payment_id is None:
        raise api_error(404, "PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")
    payment = await db.scalar(
        select(RecurringPayment)
        .where(RecurringPayment.id == payment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if payment is None:
        raise api_error(404, "PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")
    result = await db.execute(
        select(PaymentOccurrence)
        .where(PaymentOccurrence.id == occurrence_id)
        .with_for_update(of=PaymentOccurrence)
    )
    occurrence = result.scalar_one_or_none()
    if occurrence is None:
        raise api_error(404, "PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")
    if payload.paid_on is not None and payload.paid_on > today:
        raise api_error(
            422,
            "VALIDATION_ERROR",
            "Дата оплаты не может быть в будущем",
            details=[
                {
                    "field": "paid_on",
                    "code": "FUTURE_PAYMENT_DATE",
                    "message": "Укажите сегодняшнюю или более раннюю дату",
                }
            ],
        )
    previous_status, previous_paid_on = occurrence.status, occurrence.paid_on
    occurrence.status = payload.status
    occurrence.paid_on = payload.paid_on
    if actor is not None and (previous_status, previous_paid_on) != (
        occurrence.status,
        occurrence.paid_on,
    ):
        if previous_status != occurrence.status:
            action = "payment.paid" if occurrence.status == "paid" else "payment.unpaid"
        else:
            action = "payment.date_changed"
        status_labels = {"paid": "Оплачено", "unpaid": "Не оплачено"}
        record_audit_event(
            db,
            actor=actor,
            action=action,
            entity_type="payment",
            entity_id=payment.id,
            entity_title=payment.title,
            changes=[
                {
                    "field": "due_date",
                    "label": "Период со сроком",
                    "before": None,
                    "after": occurrence.due_date.isoformat(),
                },
                {
                    "field": "status",
                    "label": "Статус",
                    "before": status_labels[previous_status],
                    "after": status_labels[occurrence.status],
                },
                {
                    "field": "paid_on",
                    "label": "Дата оплаты",
                    "before": previous_paid_on.isoformat() if previous_paid_on else None,
                    "after": occurrence.paid_on.isoformat() if occurrence.paid_on else None,
                },
            ],
        )
    await db.commit()
    return occurrence_data(payment, occurrence, today)
