"""PaymentSource adapter for the reminder worker."""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_TIMEZONE, settings
from app.delivery.contracts import PaymentSnapshot
from app.models import PaymentOccurrence, RecurringPayment
from app.services.payment_periods import ensure_payment_periods


class PaymentSourceAdapter:
    def __init__(self, timezone_name: str = DEFAULT_TIMEZONE):
        self.timezone_name = timezone_name

    async def active_payment_ids(
        self, db: AsyncSession, *, after: UUID | None, limit: int
    ) -> Sequence[UUID]:
        query = select(RecurringPayment.id).where(RecurringPayment.is_active.is_(True))
        if after is not None:
            query = query.where(RecurringPayment.id > after)
        return list(await db.scalars(query.order_by(RecurringPayment.id).limit(limit)))

    async def lock_rule(self, db: AsyncSession, payment_id: UUID) -> bool:
        active = await db.scalar(
            select(RecurringPayment.is_active)
            .where(RecurringPayment.id == payment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return active is True

    async def ensure_payment_periods(
        self, db: AsyncSession, payment_id: UUID, today: date, through: date | None = None
    ) -> None:
        await ensure_payment_periods(
            db, payment_id, today, through, timezone_name=self.timezone_name
        )

    async def unpaid_occurrences(
        self, db: AsyncSession, payment_id: UUID
    ) -> Sequence[PaymentSnapshot]:
        rows = await db.execute(
            select(RecurringPayment, PaymentOccurrence)
            .join(
                PaymentOccurrence,
                PaymentOccurrence.recurring_payment_id == RecurringPayment.id,
            )
            .where(
                RecurringPayment.id == payment_id,
                PaymentOccurrence.status == "unpaid",
            )
            .order_by(PaymentOccurrence.due_date, PaymentOccurrence.id)
        )
        return [self._snapshot(payment, occurrence) for payment, occurrence in rows]

    async def occurrence(
        self, db: AsyncSession, payment_id: UUID, occurrence_id: UUID
    ) -> PaymentSnapshot | None:
        row = (
            await db.execute(
                select(RecurringPayment, PaymentOccurrence)
                .join(
                    PaymentOccurrence,
                    PaymentOccurrence.recurring_payment_id == RecurringPayment.id,
                )
                .where(
                    RecurringPayment.id == payment_id,
                    PaymentOccurrence.id == occurrence_id,
                )
            )
        ).one_or_none()
        return None if row is None else self._snapshot(*row)

    @staticmethod
    def _snapshot(payment: RecurringPayment, occurrence: PaymentOccurrence) -> PaymentSnapshot:
        return PaymentSnapshot(
            payment_id=payment.id,
            occurrence_id=occurrence.id,
            due_date=occurrence.due_date,
            title=payment.title,
            amount=payment.amount,
            currency=payment.currency,
            is_active=payment.is_active,
            is_paid=occurrence.status == "paid",
        )


def make_source() -> PaymentSourceAdapter:
    return PaymentSourceAdapter(settings.app_timezone)
