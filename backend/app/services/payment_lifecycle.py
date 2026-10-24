from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.locking import lock_payments
from app.models import PaymentOccurrence, RecurringPayment, User
from app.schemas.lifecycle import OneTimePaymentCreate
from app.services.audit import record_audit_event
from app.services.errors import api_error
from app.services.payment_periods import ensure_payment_periods
from app.services.payments import _lock_occurrence, occurrence_data


async def create_one_time_payment(
    db: AsyncSession, payload: OneTimePaymentCreate, today: date, *, actor: User, timezone_name: str
) -> dict:
    await lock_payments(db)
    payment = RecurringPayment(
        title=payload.title,
        amount=Decimal(payload.amount),
        currency=payload.currency,
        first_due_date=payload.due_date,
        periodicity="once",
        anchor_day=payload.due_date.day,
    )
    db.add(payment)
    await db.flush()
    await ensure_payment_periods(db, payment.id, today, timezone_name=timezone_name)
    occurrence = await db.scalar(
        select(PaymentOccurrence).where(PaymentOccurrence.recurring_payment_id == payment.id)
    )
    record_audit_event(
        db,
        actor=actor,
        action="payment.created",
        entity_type="payment",
        entity_id=payment.id,
        entity_title=payment.title,
        changes=[
            {
                "field": "due_date",
                "label": "Разовый срок",
                "before": None,
                "after": payload.due_date.isoformat(),
            },
            {"field": "amount", "label": "Сумма", "before": None, "after": payload.amount},
            {"field": "currency", "label": "Валюта", "before": None, "after": payload.currency},
        ],
    )
    await db.commit()
    return occurrence_data(payment, occurrence, today)


async def cancel_occurrence(db: AsyncSession, occurrence_id: UUID, *, actor: User) -> None:
    payment, occurrence = await _lock_occurrence(db, occurrence_id)
    if occurrence.status == "paid":
        raise api_error(
            409,
            "PAYMENT_ALREADY_PAID",
            "Оплаченный период нельзя удалить. Сначала отмените отметку оплаты.",
        )
    if not occurrence.is_cancelled:
        occurrence.is_cancelled = True
        if payment.periodicity == "once":
            payment.is_active = False
            payment.is_archived = True
        record_audit_event(
            db,
            actor=actor,
            action="payment.period_deleted",
            entity_type="payment",
            entity_id=payment.id,
            entity_title=payment.title,
            changes=[
                {
                    "field": "due_date",
                    "label": "Срок",
                    "before": None,
                    "after": occurrence.due_date.isoformat(),
                },
                {
                    "field": "is_cancelled",
                    "label": "Удалён из обязательств",
                    "before": "false",
                    "after": "true",
                },
            ],
        )
    await db.commit()


async def archive_payment(
    db: AsyncSession, payment_id: UUID, today: date, *, actor: User, timezone_name: str
) -> None:
    payment = await ensure_payment_periods(
        db, payment_id, today, through=today, timezone_name=timezone_name
    )
    if payment is None:
        raise api_error(404, "RECURRING_PAYMENT_NOT_FOUND", "Платёж не найден")
    if not payment.is_archived:
        payment.is_active = False
        payment.is_archived = True
        rows = await db.scalars(
            select(PaymentOccurrence)
            .where(
                PaymentOccurrence.recurring_payment_id == payment_id,
                PaymentOccurrence.status == "unpaid",
            )
            .with_for_update()
        )
        for occurrence in rows:
            occurrence.is_cancelled = True
        record_audit_event(
            db,
            actor=actor,
            action="payment.deleted",
            entity_type="payment",
            entity_id=payment.id,
            entity_title=payment.title,
            changes=[
                {
                    "field": "is_archived",
                    "label": "Удалён из списка",
                    "before": "false",
                    "after": "true",
                }
            ],
        )
    await db.commit()
