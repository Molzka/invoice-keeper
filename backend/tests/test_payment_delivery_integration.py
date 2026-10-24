from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, update

from app.delivery.queue import requeue_failed
from app.delivery.schema import deliveries
from app.delivery.worker import DeliveryWorker
from app.models import PaymentOccurrence
from app.services import payments as payment_service
from app.services.payment_source import PaymentSourceAdapter, make_source
from app.services.payments import today_in_timezone


class Sender:
    def __init__(self):
        self.calls = []

    async def __call__(self, payment):
        self.calls.append(payment)
        return 321


def freeze_payment_clock(monkeypatch, instant):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(payment_service, "datetime", FixedDateTime)


async def create_period(client, csrf_token, title, due_date):
    response = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": title,
            "amount": "123.45",
            "currency": "RUB",
            "first_due_date": due_date,
            "periodicity": "monthly",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 201, response.text
    periods = await client.get(
        "/api/v1/payment-occurrences",
        params={
            "recurring_payment_id": response.json()["id"],
            "date_from": due_date,
            "date_to": due_date,
        },
    )
    assert periods.status_code == 200, periods.text
    assert periods.json()["total"] == 1
    return periods.json()["items"][0]


async def read_delivery(db, occurrence_id):
    result = await db.execute(select(deliveries).where(deliveries.c.occurrence_id == occurrence_id))
    return dict(result.mappings().one())


async def test_real_payment_source_enqueues_sends_and_preserves_confirmed_delivery(
    client, create_user, login, app
):
    await create_user()
    auth = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    response = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Rent",
            "amount": "123.45",
            "currency": "RUB",
            "first_due_date": today.isoformat(),
            "periodicity": "monthly",
        },
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert response.status_code == 201, response.text
    payment_id = response.json()["id"]

    async with app.state.database.session_factory() as db:
        occurrence = await db.scalar(
            select(PaymentOccurrence).where(PaymentOccurrence.recurring_payment_id == payment_id)
        )
        assert occurrence is not None
        delivery = (
            (
                await db.execute(
                    select(deliveries).where(deliveries.c.occurrence_id == occurrence.id)
                )
            )
            .mappings()
            .one()
        )
        assert delivery["payment_id"] == occurrence.recurring_payment_id
        assert delivery["status"] == "pending"
        occurrence_id = occurrence.id

    price_edit = await client.patch(
        f"/api/v1/payment-occurrences/{occurrence_id}/amount",
        json={"amount": "234.56", "currency": "EUR"},
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert price_edit.status_code == 200, price_edit.text

    sender = Sender()
    worker = DeliveryWorker(app.state.database.session_factory, make_source(), sender)
    now = datetime.now(UTC)
    result = await worker.run_once(now)
    assert result["sent"] == 1
    assert [call.occurrence_id for call in sender.calls] == [occurrence_id]
    assert sender.calls[0].amount == Decimal("234.56")
    assert sender.calls[0].currency == "EUR"

    for payload in (
        {"status": "paid", "paid_on": today.isoformat()},
        {"status": "unpaid", "paid_on": None},
    ):
        changed = await client.patch(
            f"/api/v1/payment-occurrences/{occurrence_id}",
            json=payload,
            headers={"X-CSRF-Token": auth["csrf_token"]},
        )
        assert changed.status_code == 200, changed.text

    await worker.run_once(now + timedelta(minutes=1))
    async with app.state.database.session_factory() as db:
        saved = (
            (
                await db.execute(
                    select(deliveries).where(deliveries.c.occurrence_id == occurrence_id)
                )
            )
            .mappings()
            .one()
        )
        assert saved["status"] == "sent"
        assert saved["telegram_message_id"] == 321
        assert saved["sent_at"] is not None
        assert saved["occurrence_id"] == occurrence_id
    assert len(sender.calls) == 1


async def test_tokyo_midnight_drives_api_period_recovery_and_reminder_delivery(
    client, create_user, login, app, monkeypatch
):
    app.state.settings = app.state.settings.model_copy(update={"app_timezone": "Asia/Tokyo"})
    before_midnight = datetime(2026, 10, 31, 14, 59, 59, tzinfo=UTC)
    midnight = before_midnight + timedelta(seconds=1)
    freeze_payment_clock(monkeypatch, before_midnight)
    await create_user()
    auth = await login(client)
    assert auth["timezone"] == "Asia/Tokyo"
    month_end = await create_period(client, auth["csrf_token"], "Month end", "2026-10-31")
    upcoming = await create_period(client, auth["csrf_token"], "Three days ahead", "2026-11-04")
    assert month_end["is_overdue"] is False
    async with app.state.database.session_factory() as db:
        queued = await read_delivery(db, upcoming["id"])
        assert queued["scheduled_at"] == midnight
        assert queued["available_at"] == midnight
        assert queued["status"] == "pending"

    sender = Sender()
    worker = DeliveryWorker(
        app.state.database.session_factory,
        PaymentSourceAdapter("Asia/Tokyo"),
        sender,
        timezone_name="Asia/Tokyo",
    )
    before = await worker.run_once(before_midnight)
    assert before["sent"] == 1
    assert [str(call.occurrence_id) for call in sender.calls] == [month_end["id"]]
    next_month_url = (
        "/api/v1/payment-occurrences?recurring_payment_id="
        + month_end["recurring_payment_id"]
        + "&date_from=2026-11-01&date_to=2026-11-30"
    )
    assert (await client.get(next_month_url)).json()["total"] == 0

    freeze_payment_clock(monkeypatch, midnight)
    assert (await client.get(f"/api/v1/payment-occurrences/{month_end['id']}")).json()[
        "is_overdue"
    ] is True
    at_midnight = await worker.run_once(midnight)
    assert at_midnight["sent"] == 1
    assert [str(call.occurrence_id) for call in sender.calls] == [month_end["id"], upcoming["id"]]
    november = (await client.get(next_month_url)).json()
    assert november["total"] == 1
    november_period = november["items"][0]
    assert november_period["due_date"] == "2026-11-30"
    assert november_period["status"] == "unpaid"
    async with app.state.database.session_factory() as db:
        sent = await read_delivery(db, upcoming["id"])
        assert sent["status"] == "sent" and sent["sent_at"] == midnight
        assert sent["attempt_count"] == 1 and sent["telegram_message_id"] == 321
        await db.execute(
            delete(deliveries).where(deliveries.c.occurrence_id == november_period["id"])
        )
        await db.commit()

    assert await worker.recover_periods(midnight + timedelta(minutes=1)) == 2
    async with app.state.database.session_factory() as db:
        restored = await read_delivery(db, november_period["id"])
        assert restored["scheduled_at"] == datetime(2026, 11, 26, 15, tzinfo=UTC)
        assert restored["status"] == "pending" and restored["attempt_count"] == 0
        assert await read_delivery(db, upcoming["id"]) == sent

    app.state.settings = app.state.settings.model_copy(update={"app_timezone": "Europe/Moscow"})
    moscow_worker = DeliveryWorker(
        app.state.database.session_factory,
        PaymentSourceAdapter("Europe/Moscow"),
        sender,
        timezone_name="Europe/Moscow",
    )
    repeated = await moscow_worker.run_once(midnight + timedelta(hours=6, minutes=1))
    assert repeated["sent"] == 0
    async with app.state.database.session_factory() as db:
        assert await read_delivery(db, upcoming["id"]) == sent
        rescheduled = await read_delivery(db, november_period["id"])
        assert rescheduled["id"] == restored["id"]
        assert rescheduled["scheduled_at"] == datetime(2026, 11, 26, 21, tzinfo=UTC)
        assert rescheduled["available_at"] == rescheduled["scheduled_at"]
    assert len(sender.calls) == 2


async def test_timezone_recovery_reschedules_pending_and_keeps_retry_backoff(
    client, create_user, login, app, monkeypatch
):
    app.state.settings = app.state.settings.model_copy(update={"app_timezone": "Asia/Tokyo"})
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    freeze_payment_clock(monkeypatch, now)
    await create_user()
    auth = await login(client)
    periods = {
        name: await create_period(client, auth["csrf_token"], name, "2026-11-04")
        for name in ("pending", "retry_short", "retry_long", "failed_requeued")
    }
    tokyo_schedule = datetime(2026, 10, 31, 15, tzinfo=UTC)
    moscow_schedule = datetime(2026, 10, 31, 21, tzinfo=UTC)
    backoffs = {
        "retry_short": tokyo_schedule + timedelta(hours=1),
        "retry_long": moscow_schedule + timedelta(hours=1),
    }
    operator_pause = moscow_schedule + timedelta(hours=2)
    async with app.state.database.session_factory() as db:
        original = {name: await read_delivery(db, period["id"]) for name, period in periods.items()}
        assert all(row["scheduled_at"] == tokyo_schedule for row in original.values())
        for name, available_at in backoffs.items():
            await db.execute(
                update(deliveries)
                .where(deliveries.c.occurrence_id == periods[name]["id"])
                .values(
                    status="retry",
                    available_at=available_at,
                    attempt_count=2,
                    last_error_code="TELEGRAM_REJECTED_RETRYABLE",
                )
            )
        await db.execute(
            update(deliveries)
            .where(deliveries.c.occurrence_id == periods["failed_requeued"]["id"])
            .values(
                status="failed",
                available_at=operator_pause,
                attempt_count=5,
                last_error_code="TELEGRAM_REJECTED_RETRYABLE",
            )
        )
        await db.commit()
        await requeue_failed(db, original["failed_requeued"]["id"], now=now)
        await db.commit()
        requeued = await read_delivery(db, periods["failed_requeued"]["id"])
        assert requeued["status"] == "pending" and requeued["attempt_count"] == 0
        assert requeued["available_at"] == operator_pause
        assert requeued["last_error_code"] is None

    sender = Sender()
    for timezone_name, scheduled_at in (
        ("Europe/Moscow", moscow_schedule),
        ("Asia/Tokyo", tokyo_schedule),
    ):
        worker = DeliveryWorker(
            app.state.database.session_factory,
            PaymentSourceAdapter(timezone_name),
            sender,
            timezone_name=timezone_name,
        )
        assert await worker.recover_periods(now) == 4
        async with app.state.database.session_factory() as db:
            for name, period in periods.items():
                row = await read_delivery(db, period["id"])
                assert row["id"] == original[name]["id"]
                assert row["scheduled_at"] == scheduled_at
                if name == "pending":
                    assert row["status"] == "pending" and row["attempt_count"] == 0
                    assert row["available_at"] == scheduled_at
                elif name == "failed_requeued":
                    assert row["status"] == "pending" and row["attempt_count"] == 0
                    assert row["available_at"] == operator_pause
                    assert row["last_error_code"] is None
                else:
                    assert row["status"] == "retry" and row["attempt_count"] == 2
                    assert row["available_at"] == max(backoffs[name], moscow_schedule)
                    assert row["last_error_code"] == "TELEGRAM_REJECTED_RETRYABLE"
        assert (await worker.run_once(now))["sent"] == 0
    assert sender.calls == []
    assert (await worker.run_once(operator_pause - timedelta(seconds=1)))["sent"] == 3
    assert periods["failed_requeued"]["id"] not in {
        str(call.occurrence_id) for call in sender.calls
    }
    assert (await worker.run_once(operator_pause))["sent"] == 1
    assert str(sender.calls[-1].occurrence_id) == periods["failed_requeued"]["id"]
