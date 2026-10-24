import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update

from app.delivery.contracts import PermanentRejection, RetryableRejection
from app.delivery.locking import lock_payments
from app.delivery.queue import enqueue_payment_reminder, reminder_at, resolve_unknown
from app.delivery.schema import deliveries
from app.delivery.telegram import build_reminder_text
from app.delivery.worker import DeliveryWorker

from .delivery_helpers import TestPaymentSource, add_payment, periods, rules

NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
pytestmark = pytest.mark.asyncio


class Sender:
    def __init__(self, *outcomes):
        self.calls = []
        self.outcomes = list(outcomes)

    async def __call__(self, snapshot):
        self.calls.append(snapshot)
        result = self.outcomes.pop(0) if self.outcomes else 777
        if isinstance(result, BaseException):
            raise result
        return result


def worker(database, sender=None, **kwargs):
    return DeliveryWorker(
        database.session_factory, TestPaymentSource(), sender or Sender(), **kwargs
    )


async def row_for(database, occurrence_id):
    async with database.session_factory() as db:
        return (
            (
                await db.execute(
                    select(deliveries).where(deliveries.c.occurrence_id == occurrence_id)
                )
            )
            .mappings()
            .one()
        )


async def queue(database, payment_id, occurrence_id, due_date=date(2026, 11, 10)):
    async with database.session_factory() as db, db.begin():
        await lock_payments(db)
        await TestPaymentSource().lock_rule(db, payment_id)
        return await enqueue_payment_reminder(
            db, payment_id=payment_id, occurrence_id=occurrence_id, due_date=due_date, now=NOW
        )


@pytest.mark.parametrize(
    "due,expected",
    [
        (date(2026, 11, 10), datetime(2026, 11, 6, 21, tzinfo=UTC)),
        (date(2027, 1, 2), datetime(2026, 12, 29, 21, tzinfo=UTC)),
        (date(2028, 3, 1), datetime(2028, 2, 26, 21, tzinfo=UTC)),
    ],
)
async def test_midnight_moscow_three_calendar_days_before_due(due, expected):
    assert reminder_at(due) == expected


async def test_rule_period_and_queue_rollback_together(delivery_db):
    payment_id = uuid4()
    async with delivery_db.session_factory() as db:
        await lock_payments(db)
        await db.execute(
            rules.insert().values(
                id=payment_id,
                title="Atomic",
                due_date=date(2026, 11, 10),
                is_active=True,
                ensure_calls=0,
            )
        )
        source = TestPaymentSource()
        await source.lock_rule(db, payment_id)
        await source.ensure_payment_periods(db, payment_id, NOW.date())
        snapshot = (await source.unpaid_occurrences(db, payment_id))[0]
        await enqueue_payment_reminder(
            db,
            payment_id=payment_id,
            occurrence_id=snapshot.occurrence_id,
            due_date=snapshot.due_date,
            now=NOW,
        )
        async with delivery_db.session_factory() as observer:
            assert await observer.scalar(select(func.count()).select_from(deliveries)) == 0
        await db.rollback()
    async with delivery_db.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(rules)) == 0
        assert await db.scalar(select(func.count()).select_from(periods)) == 0
        assert await db.scalar(select(func.count()).select_from(deliveries)) == 0


async def test_concurrent_enqueue_is_unique_and_never_commits_separately(delivery_db):
    payment_id, occurrence_id = await add_payment(delivery_db)
    ids = await asyncio.gather(*[queue(delivery_db, payment_id, occurrence_id) for _ in range(4)])
    assert len(set(ids)) == 1
    row = await row_for(delivery_db, occurrence_id)
    assert row["available_at"] < NOW and row["status"] == "pending"


async def test_recovery_uses_shared_service_and_sends_past_due_immediately(delivery_db):
    payment_id, _ = await add_payment(delivery_db, create_period=False)
    sender = Sender()
    result = await worker(delivery_db, sender).run_once(NOW)
    assert result == {"recovered": 1, "processed": 1, "sent": 1}
    async with delivery_db.session_factory() as db:
        assert await db.scalar(select(rules.c.ensure_calls).where(rules.c.id == payment_id)) == 1
        row = (await db.execute(select(deliveries))).mappings().one()
        assert (
            row["status"] == "sent" and row["telegram_message_id"] == 777 and row["sent_at"] == NOW
        )
    assert len(sender.calls) == 1
    assert "&lt;rent&gt;" in build_reminder_text(sender.calls[0])


async def test_future_schedule_does_not_send_early(delivery_db):
    await add_payment(delivery_db, due_date=date(2026, 12, 10))
    sender = Sender()
    assert (await worker(delivery_db, sender).run_once(NOW))["sent"] == 0
    assert sender.calls == []


async def test_schedule_boundary_and_restart_preserve_single_delivery(delivery_db):
    due_date = date(2026, 11, 10)
    _, occurrence_id = await add_payment(delivery_db, due_date=due_date)
    scheduled_at = reminder_at(due_date)
    sender = Sender()
    engine = worker(delivery_db, sender)

    assert (await engine.run_once(scheduled_at - timedelta(microseconds=1)))["sent"] == 0
    assert (await engine.run_once(scheduled_at))["sent"] == 1
    confirmed = dict(await row_for(delivery_db, occurrence_id))
    assert (await worker(delivery_db, sender).run_once(scheduled_at + timedelta(days=1)))[
        "sent"
    ] == 0
    assert dict(await row_for(delivery_db, occurrence_id)) == confirmed
    assert len(sender.calls) == 1


@pytest.mark.parametrize("days_until_due", [2, 0, -7])
async def test_late_added_period_is_ready_in_first_cycle(delivery_db, days_until_due):
    due_date = NOW.date() + timedelta(days=days_until_due)
    _, occurrence_id = await add_payment(delivery_db, due_date=due_date)
    sender = Sender()

    assert (await worker(delivery_db, sender).run_once(NOW))["sent"] == 1
    row = await row_for(delivery_db, occurrence_id)
    assert row["scheduled_at"] == reminder_at(due_date) < NOW
    assert row["sent_at"] == NOW
    assert len(sender.calls) == 1


@pytest.mark.parametrize("state", ["paid", "stopped"])
async def test_recovery_does_not_queue_paid_or_stopped_periods(delivery_db, state):
    await add_payment(delivery_db, paid=state == "paid", active=state != "stopped")
    sender = Sender()

    assert (await worker(delivery_db, sender).run_once(NOW))["sent"] == 0
    assert sender.calls == []
    async with delivery_db.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(deliveries)) == 0


async def test_each_period_has_independent_payment_and_delivery_state(delivery_db):
    payment_id, paid_period_id = await add_payment(delivery_db, paid=True)
    unpaid_period_id = uuid4()
    async with delivery_db.session_factory() as db, db.begin():
        await lock_payments(db)
        await TestPaymentSource().lock_rule(db, payment_id)
        await db.execute(
            periods.insert().values(
                id=unpaid_period_id,
                payment_id=payment_id,
                due_date=date(2026, 10, 10),
                is_paid=False,
                amount=Decimal("123.45"),
                currency="RUB",
            )
        )
    sender = Sender()
    assert (await worker(delivery_db, sender).run_once(NOW))["sent"] == 1
    assert [item.occurrence_id for item in sender.calls] == [unpaid_period_id]

    async with delivery_db.session_factory() as db, db.begin():
        await lock_payments(db)
        await TestPaymentSource().lock_rule(db, payment_id)
        await db.execute(
            update(periods).where(periods.c.id == paid_period_id).values(is_paid=False)
        )
    assert (await worker(delivery_db, sender).run_once(NOW + timedelta(minutes=1)))["sent"] == 1
    assert [item.occurrence_id for item in sender.calls] == [unpaid_period_id, paid_period_id]
    assert (await worker(delivery_db, sender).run_once(NOW + timedelta(days=1)))["sent"] == 0
    async with delivery_db.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(deliveries)) == 2


@pytest.mark.parametrize("change", ["paid", "inactive"])
async def test_latest_state_is_rechecked_between_claim_and_network(delivery_db, change):
    payment_id, occurrence_id = await add_payment(delivery_db)
    await queue(delivery_db, payment_id, occurrence_id)
    sender = Sender()
    engine = worker(delivery_db, sender)
    claim, _ = await engine.claim_one(NOW)
    async with delivery_db.session_factory() as db, db.begin():
        await lock_payments(db)
        await TestPaymentSource().lock_rule(db, payment_id)
        if change == "paid":
            await db.execute(
                update(periods).where(periods.c.id == occurrence_id).values(is_paid=True)
            )
        else:
            await db.execute(update(rules).where(rules.c.id == payment_id).values(is_active=False))
    assert not await engine.send_claim(claim, NOW)
    assert sender.calls == []
    assert (await row_for(delivery_db, occurrence_id))["status"] == (
        "pending" if change == "paid" else "cancelled"
    )


async def test_confirmed_delivery_survives_payment_toggle_and_reenqueue(delivery_db):
    payment_id, occurrence_id = await add_payment(delivery_db)
    sender = Sender()
    engine = worker(delivery_db, sender)
    await engine.run_once(NOW)
    original = dict(await row_for(delivery_db, occurrence_id))
    for paid in (True, False):
        async with delivery_db.session_factory() as db, db.begin():
            await lock_payments(db)
            await TestPaymentSource().lock_rule(db, payment_id)
            await db.execute(
                update(periods).where(periods.c.id == occurrence_id).values(is_paid=paid)
            )
            await enqueue_payment_reminder(
                db,
                payment_id=payment_id,
                occurrence_id=occurrence_id,
                due_date=date(2026, 11, 10),
                now=NOW,
            )
        await engine.run_once(NOW + timedelta(minutes=1))
    assert dict(await row_for(delivery_db, occurrence_id)) == original
    assert len(sender.calls) == 1


async def test_paid_unsent_period_can_send_after_unpay(delivery_db):
    payment_id, occurrence_id = await add_payment(delivery_db, paid=True)
    await queue(delivery_db, payment_id, occurrence_id)
    sender = Sender()
    engine = worker(delivery_db, sender)
    await engine.run_once(NOW)
    assert not sender.calls
    async with delivery_db.session_factory() as db, db.begin():
        await lock_payments(db)
        await TestPaymentSource().lock_rule(db, payment_id)
        await db.execute(update(periods).where(periods.c.id == occurrence_id).values(is_paid=False))
    assert (await engine.run_once(NOW + timedelta(minutes=1)))["sent"] == 1


@pytest.mark.parametrize(
    "error", [TimeoutError(), ConnectionError("private-token"), RuntimeError("private-token")]
)
async def test_unknown_result_is_not_retried_and_does_not_store_exception_text(delivery_db, error):
    payment_id, occurrence_id = await add_payment(delivery_db)
    sender = Sender(error)
    engine = worker(delivery_db, sender)
    await engine.run_once(NOW)
    await queue(delivery_db, payment_id, occurrence_id)
    await engine.run_once(NOW + timedelta(days=2))
    row = await row_for(delivery_db, occurrence_id)
    assert row["status"] == "unknown" and len(sender.calls) == 1
    assert "private-token" not in str(dict(row))


async def test_interrupted_attempt_becomes_unknown_without_network_replay(delivery_db):
    payment_id, occurrence_id = await add_payment(delivery_db)
    await queue(delivery_db, payment_id, occurrence_id)
    sender = Sender(asyncio.CancelledError())
    engine = worker(delivery_db, sender)
    claim, _ = await engine.claim_one(NOW)
    assert (await row_for(delivery_db, occurrence_id))["status"] == "in_flight"
    with pytest.raises(asyncio.CancelledError):
        await engine.send_claim(claim, NOW)
    await worker(delivery_db, sender).run_once(NOW + timedelta(minutes=3))
    assert (await row_for(delivery_db, occurrence_id))["status"] == "unknown"
    assert len(sender.calls) == 1


async def test_safe_rejection_retries_after_backoff_then_confirms(delivery_db):
    _, occurrence_id = await add_payment(delivery_db)
    sender = Sender(RetryableRejection(120), 888)
    engine = worker(delivery_db, sender)
    await engine.run_once(NOW)
    assert (await row_for(delivery_db, occurrence_id))["status"] == "retry"
    assert (await engine.run_once(NOW + timedelta(seconds=119)))["sent"] == 0
    assert (await engine.run_once(NOW + timedelta(seconds=120)))["sent"] == 1
    row = await row_for(delivery_db, occurrence_id)
    assert (
        row["status"] == "sent" and row["attempt_count"] == 2 and row["telegram_message_id"] == 888
    )


@pytest.mark.parametrize("change", ["paid", "inactive"])
async def test_retry_rechecks_payment_and_rule_state(delivery_db, change):
    payment_id, occurrence_id = await add_payment(delivery_db)
    sender = Sender(RetryableRejection(120))
    engine = worker(delivery_db, sender)
    await engine.run_once(NOW)
    assert (await row_for(delivery_db, occurrence_id))["status"] == "retry"
    async with delivery_db.session_factory() as db, db.begin():
        await lock_payments(db)
        await TestPaymentSource().lock_rule(db, payment_id)
        if change == "paid":
            await db.execute(
                update(periods).where(periods.c.id == occurrence_id).values(is_paid=True)
            )
        else:
            await db.execute(update(rules).where(rules.c.id == payment_id).values(is_active=False))

    assert (await worker(delivery_db, sender).run_once(NOW + timedelta(minutes=3)))["sent"] == 0
    assert len(sender.calls) == 1
    assert (await row_for(delivery_db, occurrence_id))["status"] == (
        "pending" if change == "paid" else "cancelled"
    )


@pytest.mark.parametrize(
    "outcomes", [[PermanentRejection()], [RetryableRejection(1), RetryableRejection(1)]]
)
async def test_permanent_or_exhausted_safe_retries_are_failed(delivery_db, outcomes):
    _, occurrence_id = await add_payment(delivery_db)
    sender = Sender(*outcomes)
    engine = worker(delivery_db, sender, max_attempts=2)
    await engine.run_once(NOW)
    await engine.run_once(NOW + timedelta(minutes=5))
    assert (await row_for(delivery_db, occurrence_id))["status"] == "failed"


async def test_two_workers_do_not_send_the_same_period_twice(delivery_db):
    await add_payment(delivery_db)
    sender = Sender()
    await asyncio.gather(
        worker(delivery_db, sender).run_once(NOW), worker(delivery_db, sender).run_once(NOW)
    )
    assert len(sender.calls) == 1


async def test_stop_waits_for_started_send_and_prevents_subsequent_sends(delivery_db):
    payment_id, occurrence_id = await add_payment(delivery_db)
    await queue(delivery_db, payment_id, occurrence_id)
    started, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def sender(snapshot):
        started.set()
        await release.wait()
        return 555

    engine = worker(delivery_db, sender)
    claim, _ = await engine.claim_one(NOW)
    sending = asyncio.create_task(engine.send_claim(claim, NOW))
    await asyncio.wait_for(started.wait(), 2)

    async def stop():
        async with delivery_db.session_factory() as db, db.begin():
            await lock_payments(db)
            await TestPaymentSource().lock_rule(db, payment_id)
            await db.execute(update(rules).where(rules.c.id == payment_id).values(is_active=False))
        stopped.set()

    stopping = asyncio.create_task(stop())
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(stopped.wait(), 0.05)
    finally:
        release.set()
        await asyncio.gather(sending, stopping)
    assert stopped.is_set()
    assert (await row_for(delivery_db, occurrence_id))["status"] == "sent"


@pytest.mark.parametrize("outcome", ["sent", "not_sent"])
async def test_unknown_requires_explicit_operator_resolution(delivery_db, outcome):
    _, occurrence_id = await add_payment(delivery_db)
    sender = Sender(TimeoutError(), 909)
    engine = worker(delivery_db, sender)
    await engine.run_once(NOW)
    row = await row_for(delivery_db, occurrence_id)
    async with delivery_db.session_factory() as db, db.begin():
        await resolve_unknown(
            db,
            row["id"],
            outcome=outcome,
            telegram_message_id=321 if outcome == "sent" else None,
            now=NOW,
        )
    await engine.run_once(NOW + timedelta(minutes=1))
    assert (await row_for(delivery_db, occurrence_id))["status"] == "sent"
    assert len(sender.calls) == (1 if outcome == "sent" else 2)
    async with delivery_db.session_factory() as db:
        with pytest.raises(ValueError):
            await resolve_unknown(db, row["id"], outcome="not_sent", now=NOW)


async def test_real_send_timeout_leaves_unknown_not_retry(delivery_db):
    _, occurrence_id = await add_payment(delivery_db)

    async def slow_sender(snapshot):
        await asyncio.sleep(10)
        return 1

    engine = worker(delivery_db, slow_sender, send_timeout=0.01)
    await engine.run_once(NOW)
    assert (await row_for(delivery_db, occurrence_id))["status"] == "unknown"


async def test_commit_failure_after_acknowledgement_never_automatically_replays(delivery_db):
    payment_id, occurrence_id = await add_payment(delivery_db)
    await queue(delivery_db, payment_id, occurrence_id)
    sender = Sender()
    engine = worker(delivery_db, sender)
    claim, _ = await engine.claim_one(NOW)

    def fail_commit(connection):
        raise RuntimeError("Simulated commit failure after Telegram acknowledgement")

    event.listen(delivery_db.engine.sync_engine, "commit", fail_commit, once=True)
    try:
        with pytest.raises(RuntimeError, match="Simulated commit failure"):
            await engine.send_claim(claim, NOW)
    finally:
        event.remove(delivery_db.engine.sync_engine, "commit", fail_commit)
    assert (await row_for(delivery_db, occurrence_id))["status"] == "in_flight"
    await worker(delivery_db, sender).run_once(NOW + timedelta(minutes=3))
    assert (await row_for(delivery_db, occurrence_id))["status"] == "unknown"
    assert len(sender.calls) == 1
