from calendar import monthrange
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.delivery.locking import lock_payments
from app.delivery.queue import enqueue_payment_reminder
from app.models import PaymentOccurrence, RecurringPayment
from app.services.payment_calendar import monthly_due_dates, next_due_date


def active_generation_end(payment: RecurringPayment, today: date) -> date:
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    return max(month_end, next_due_date(payment.first_due_date, payment.anchor_day, today))


async def create_missing_periods(
    db: AsyncSession,
    payment: RecurringPayment,
    through: date,
) -> None:
    due_dates = monthly_due_dates(payment.first_due_date, payment.anchor_day, through)
    if not due_dates:
        return
    existing = set(
        await db.scalars(
            select(PaymentOccurrence.due_date).where(
                PaymentOccurrence.recurring_payment_id == payment.id,
                PaymentOccurrence.due_date.between(payment.first_due_date, through),
            )
        )
    )
    missing = [due_date for due_date in due_dates if due_date not in existing]
    for offset in range(0, len(missing), 1000):
        batch = missing[offset : offset + 1000]
        inserted = await db.execute(
            insert(PaymentOccurrence)
            .values(
                [
                    {
                        "id": uuid4(),
                        "recurring_payment_id": payment.id,
                        "due_date": due_date,
                        "status": "unpaid",
                    }
                    for due_date in batch
                ]
            )
            .on_conflict_do_nothing(index_elements=["recurring_payment_id", "due_date"])
            .returning(PaymentOccurrence.id, PaymentOccurrence.due_date)
        )
        for occurrence_id, due_date in inserted:
            await enqueue_payment_reminder(
                db,
                payment_id=payment.id,
                occurrence_id=occurrence_id,
                due_date=due_date,
            )


async def ensure_payment_periods(
    db: AsyncSession,
    payment_id: UUID,
    today: date,
    through: date | None = None,
) -> RecurringPayment | None:
    """Lock a rule and fill periods without committing the caller's transaction."""
    await lock_payments(db)
    payment = await db.scalar(
        select(RecurringPayment)
        .where(RecurringPayment.id == payment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if payment is not None and payment.is_active:
        await create_missing_periods(
            db,
            payment,
            through if through is not None else active_generation_end(payment, today),
        )
    return payment
