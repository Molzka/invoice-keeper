from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class PaymentSnapshot:
    payment_id: UUID
    occurrence_id: UUID
    due_date: date
    title: str
    amount: Decimal
    currency: str
    is_active: bool
    is_paid: bool


class PaymentSource(Protocol):
    """Participant 2 implements these methods using the same AsyncSession.

    No method commits. lock_rule takes SELECT FOR UPDATE and returns True only
    when the recurring rule still exists and is active.
    active_payment_ids returns UUIDs in ascending order, strictly after `after`.
    The worker acquires the global advisory lock before calling these methods.
    """

    async def active_payment_ids(
        self, db: AsyncSession, *, after: UUID | None, limit: int
    ) -> Sequence[UUID]: ...

    async def lock_rule(self, db: AsyncSession, payment_id: UUID) -> bool: ...

    async def ensure_payment_periods(
        self, db: AsyncSession, payment_id: UUID, today: date, through: date | None = None
    ) -> None: ...

    async def unpaid_occurrences(
        self, db: AsyncSession, payment_id: UUID
    ) -> Sequence[PaymentSnapshot]: ...

    async def occurrence(
        self, db: AsyncSession, payment_id: UUID, occurrence_id: UUID
    ) -> PaymentSnapshot | None: ...


class ReminderSender(Protocol):
    async def __call__(self, payment: PaymentSnapshot) -> int:
        """One network attempt; return the confirmed Telegram message_id."""
        ...


class RetryableRejection(Exception):
    """Telegram explicitly rejected the request; it is safe to retry later."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = max(1, retry_after)


class PermanentRejection(Exception):
    """Telegram explicitly rejected the request; operator action is required."""
