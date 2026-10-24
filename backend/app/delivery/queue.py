from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_TIMEZONE
from app.delivery.locking import lock_payments
from app.delivery.schema import deliveries


def reminder_at(due_date: date, timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    zone = ZoneInfo(timezone_name)
    try:
        return datetime.combine(due_date - timedelta(days=3), time.min, zone).astimezone(UTC)
    except OverflowError:
        # The API accepts year 0001; its earliest reminders predate Python's
        # datetime range. They are already due, including after UTC conversion.
        return datetime.min.replace(tzinfo=UTC)


def utc_time(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Use a timezone-aware datetime")
    return value.astimezone(UTC)


async def enqueue_payment_reminder(
    db: AsyncSession,
    *,
    payment_id: UUID,
    occurrence_id: UUID,
    due_date: date,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> UUID:
    """Insert once in the caller's transaction; never commit, reset or send.

    Caller holds lock_payments(db), then the rule row lock, and has flushed the
    rule/occurrence. Queue even overdue items with their original UTC schedule.
    """
    now = utc_time(now)
    await db.flush()
    scheduled_at = reminder_at(due_date, timezone_name)
    inserted = await db.scalar(
        insert(deliveries)
        .values(
            id=uuid4(),
            payment_id=payment_id,
            occurrence_id=occurrence_id,
            scheduled_at=scheduled_at,
            available_at=scheduled_at,
            status="pending",
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[deliveries.c.occurrence_id])
        .returning(deliveries.c.id)
    )
    if inserted is not None:
        return inserted
    existing = (
        await db.execute(
            select(
                deliveries.c.id,
                deliveries.c.payment_id,
                deliveries.c.status,
                deliveries.c.scheduled_at,
            ).where(deliveries.c.occurrence_id == occurrence_id)
        )
    ).one()
    if existing.payment_id != payment_id:
        raise ValueError("Occurrence already belongs to a different payment")
    # Reconcile changed calendar settings without resetting retries or outcomes.
    if existing.status in {"pending", "retry"} and existing.scheduled_at != scheduled_at:
        await db.execute(
            update(deliveries)
            .where(deliveries.c.id == existing.id)
            .values(
                scheduled_at=scheduled_at,
                available_at=case(
                    (
                        or_(
                            deliveries.c.status == "retry",
                            deliveries.c.available_at != deliveries.c.scheduled_at,
                        ),
                        func.greatest(deliveries.c.available_at, scheduled_at),
                    ),
                    else_=scheduled_at,
                ),
                updated_at=now,
            )
        )
    return existing.id


async def requeue_failed(
    db: AsyncSession,
    delivery_id: UUID,
    *,
    now: datetime | None = None,
) -> None:
    """Operator retry after fixing the cause; only unconfirmed failed jobs.

    Reset the retry budget, retaining the same job and any remaining backoff.
    Never commit or send: the worker must recheck the payment before delivery.
    """
    now = utc_time(now)
    await lock_payments(db)
    updated = await db.scalar(
        update(deliveries)
        .where(
            deliveries.c.id == delivery_id,
            deliveries.c.status == "failed",
            deliveries.c.sent_at.is_(None),
            deliveries.c.telegram_message_id.is_(None),
        )
        .values(
            status="pending",
            available_at=func.greatest(deliveries.c.available_at, now),
            attempt_count=0,
            attempt_id=None,
            lease_until=None,
            last_error_code=None,
            updated_at=now,
        )
        .returning(deliveries.c.id)
    )
    if updated is None:
        raise ValueError("Only a failed delivery without confirmation can be requeued")


async def resolve_unknown(
    db: AsyncSession,
    delivery_id: UUID,
    *,
    outcome: Literal["sent", "not_sent"],
    telegram_message_id: int | None = None,
    now: datetime | None = None,
) -> None:
    """Operator decision, not an automatic retry. Caller commits the decision."""
    now = utc_time(now)
    if outcome not in {"sent", "not_sent"}:
        raise ValueError("Outcome must be sent or not_sent")
    if outcome == "sent" and (telegram_message_id is None or telegram_message_id <= 0):
        raise ValueError("A confirmed Telegram message_id is required")
    await lock_payments(db)
    row = (
        (
            await db.execute(
                select(deliveries).where(deliveries.c.id == delivery_id).with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["status"] != "unknown":
        raise ValueError("Only an unknown delivery can be resolved")
    values = {"updated_at": now, "lease_until": None, "attempt_id": None, "last_error_code": None}
    if outcome == "sent":
        values.update(status="sent", sent_at=now, telegram_message_id=telegram_message_id)
    else:
        values.update(status="pending", available_at=now)
    await db.execute(update(deliveries).where(deliveries.c.id == delivery_id).values(**values))
