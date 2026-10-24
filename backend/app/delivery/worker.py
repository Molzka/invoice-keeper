"""Delivery engine. PaymentSource is injected; it is owned by participant 2."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.delivery.contracts import (
    PaymentSnapshot,
    PaymentSource,
    PermanentRejection,
    ReminderSender,
    RetryableRejection,
)
from app.delivery.locking import lock_payments
from app.delivery.queue import MOSCOW, enqueue_payment_reminder, reminder_at, utc_time
from app.delivery.schema import deliveries


@dataclass(frozen=True, slots=True)
class Claim:
    delivery_id: UUID
    payment_id: UUID
    occurrence_id: UUID
    attempt_id: UUID


class DeliveryWorker:
    def __init__(
        self,
        sessions: async_sessionmaker,
        source: PaymentSource,
        sender: ReminderSender,
        *,
        batch_size: int = 100,
        send_timeout: float = 20,
        poll_seconds: int = 30,
        max_attempts: int = 5,
    ):
        if batch_size < 1 or send_timeout <= 0 or poll_seconds < 1 or max_attempts < 1:
            raise ValueError("Worker limits must be positive")
        self.sessions, self.source, self.sender = sessions, source, sender
        self.batch_size, self.send_timeout = batch_size, send_timeout
        self.poll_seconds, self.max_attempts = poll_seconds, max_attempts
        self.recovery_cursor: UUID | None = None

    async def recover_periods(self, now: datetime | None = None) -> int:
        now = utc_time(now)
        async with self.sessions() as db, db.begin():
            await lock_payments(db)
            ids = await self.source.active_payment_ids(
                db, after=self.recovery_cursor, limit=self.batch_size
            )
        if not ids:
            self.recovery_cursor = None
            return 0
        if list(ids) != sorted(set(ids)) or (
            self.recovery_cursor and ids[0] <= self.recovery_cursor
        ):
            raise ValueError("PaymentSource must paginate by strictly increasing UUID")
        for payment_id in ids:
            async with self.sessions() as db, db.begin():
                await lock_payments(db)
                if await self.source.lock_rule(db, payment_id):
                    await self.source.ensure_payment_periods(
                        db, payment_id, now.astimezone(MOSCOW).date()
                    )
                    for item in await self.source.unpaid_occurrences(db, payment_id):
                        if item.payment_id != payment_id:
                            raise ValueError(
                                "PaymentSource returned an occurrence from another rule"
                            )
                        if item.is_active and not item.is_paid:
                            await enqueue_payment_reminder(
                                db,
                                payment_id=payment_id,
                                occurrence_id=item.occurrence_id,
                                due_date=item.due_date,
                                now=now,
                            )
            self.recovery_cursor = payment_id
        if len(ids) < self.batch_size:
            self.recovery_cursor = None
        return len(ids)

    async def _eligible(self, db, row, snapshot: PaymentSnapshot | None, now: datetime) -> bool:
        values = None
        if snapshot is None or not snapshot.is_active:
            values = {"status": "cancelled", "last_error_code": "RULE_INACTIVE_OR_MISSING"}
        else:
            if (
                snapshot.payment_id != row["payment_id"]
                or snapshot.occurrence_id != row["occurrence_id"]
            ):
                raise ValueError("PaymentSource returned the wrong occurrence")
            scheduled_at = reminder_at(snapshot.due_date)
            if snapshot.is_paid:
                # Keep the job resumable if payment is later undone; never touch sent.
                values = {
                    "status": "pending",
                    "available_at": now + timedelta(seconds=self.poll_seconds),
                    "last_error_code": "PERIOD_PAID",
                }
            elif scheduled_at > now:
                values = {
                    "status": "pending",
                    "scheduled_at": scheduled_at,
                    "available_at": scheduled_at,
                    "last_error_code": None,
                }
        if values is None:
            return True
        await db.execute(
            update(deliveries)
            .where(deliveries.c.id == row["id"])
            .values(**values, attempt_id=None, lease_until=None, updated_at=now)
        )
        return False

    async def claim_one(self, now: datetime | None = None) -> tuple[Claim | None, bool]:
        now = utc_time(now)
        async with self.sessions() as db, db.begin():
            await lock_payments(db)
            ready = or_(
                and_(
                    deliveries.c.status.in_(["pending", "retry"]), deliveries.c.available_at <= now
                ),
                and_(deliveries.c.status == "in_flight", deliveries.c.lease_until <= now),
            )
            row = (
                (
                    await db.execute(
                        select(deliveries)
                        .where(ready)
                        .order_by(deliveries.c.available_at, deliveries.c.id)
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None, False
            if row["status"] == "in_flight":
                # A crashed attempt might already have reached Telegram. No replay.
                await db.execute(
                    update(deliveries)
                    .where(deliveries.c.id == row["id"])
                    .values(
                        status="unknown",
                        last_error_code="ATTEMPT_INTERRUPTED",
                        lease_until=None,
                        updated_at=now,
                    )
                )
                return None, True
            exists = await self.source.lock_rule(db, row["payment_id"])
            snapshot = (
                (await self.source.occurrence(db, row["payment_id"], row["occurrence_id"]))
                if exists
                else None
            )
            if not await self._eligible(db, row, snapshot, now):
                return None, True
            attempt_id = uuid4()
            await db.execute(
                update(deliveries)
                .where(deliveries.c.id == row["id"])
                .values(
                    status="in_flight",
                    attempt_id=attempt_id,
                    attempt_count=row["attempt_count"] + 1,
                    last_error_code=None,
                    lease_until=now + timedelta(seconds=self.send_timeout + 60),
                    updated_at=now,
                )
            )
            return Claim(row["id"], row["payment_id"], row["occurrence_id"], attempt_id), True

    async def send_claim(self, claim: Claim, now: datetime | None = None) -> bool:
        # claim_one already committed in_flight before any possible network call.
        # Hold the shared protocol's transaction lock through the bounded attempt:
        # rule stop/payment changes cannot commit between the last check and send.
        fixed_now = now
        async with self.sessions() as db, db.begin():
            await lock_payments(db)
            now = utc_time(now)
            exists = await self.source.lock_rule(db, claim.payment_id)
            row = (
                (
                    await db.execute(
                        select(deliveries)
                        .where(deliveries.c.id == claim.delivery_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["status"] != "in_flight" or row["attempt_id"] != claim.attempt_id:
                return False
            if row["lease_until"] <= now:
                await db.execute(
                    update(deliveries)
                    .where(deliveries.c.id == claim.delivery_id)
                    .values(
                        status="unknown",
                        last_error_code="ATTEMPT_EXPIRED",
                        lease_until=None,
                        updated_at=now,
                    )
                )
                return False
            snapshot = (
                (await self.source.occurrence(db, claim.payment_id, claim.occurrence_id))
                if exists
                else None
            )
            if not await self._eligible(db, row, snapshot, now):
                return False
            try:
                async with asyncio.timeout(self.send_timeout):
                    message_id = await self.sender(snapshot)
                if (
                    not isinstance(message_id, int)
                    or isinstance(message_id, bool)
                    or message_id <= 0
                ):
                    raise ValueError("No confirmed Telegram message_id")
            except RetryableRejection as exc:
                finished_at = utc_time(fixed_now)
                status = "failed" if row["attempt_count"] >= self.max_attempts else "retry"
                values = {
                    "status": status,
                    "last_error_code": "TELEGRAM_REJECTED_RETRYABLE",
                    "available_at": finished_at
                    + timedelta(
                        seconds=max(
                            exc.retry_after, min(3600, 30 * 2 ** min(row["attempt_count"], 7))
                        )
                    ),
                }
            except PermanentRejection:
                values = {"status": "failed", "last_error_code": "TELEGRAM_REJECTED_PERMANENT"}
            except Exception:
                # Includes timeout, network/5xx, invalid acknowledgement, and unknown
                # transport failures. Never store exception text (may contain secrets).
                values = {"status": "unknown", "last_error_code": "TELEGRAM_OUTCOME_UNKNOWN"}
            else:
                values = {
                    "status": "sent",
                    "telegram_message_id": message_id,
                    "sent_at": utc_time(fixed_now),
                    "last_error_code": None,
                }
            # Cancellation or commit failure leaves durable in_flight; its lease
            # later becomes unknown, even if Telegram accepted the message.
            await db.execute(
                update(deliveries)
                .where(deliveries.c.id == claim.delivery_id)
                .values(**values, lease_until=None, updated_at=utc_time(fixed_now))
            )
            return values["status"] == "sent"

    async def run_once(self, now: datetime | None = None) -> dict[str, int]:
        recovered = await self.recover_periods(now)
        processed = sent = 0
        for _ in range(self.batch_size):
            claim, had_work = await self.claim_one(now)
            if not had_work:
                break
            processed += 1
            if claim is not None:
                sent += await self.send_claim(claim, now)
        return {"recovered": recovered, "processed": processed, "sent": sent}
