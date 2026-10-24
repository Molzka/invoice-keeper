from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.delivery.schema import deliveries
from app.delivery.worker import DeliveryWorker
from app.models import PaymentOccurrence
from app.services.payment_source import make_source
from app.services.payments import today_in_timezone


class Sender:
    def __init__(self):
        self.calls = []

    async def __call__(self, payment):
        self.calls.append(payment)
        return 321


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

    sender = Sender()
    worker = DeliveryWorker(app.state.database.session_factory, make_source(), sender)
    now = datetime.now(UTC)
    result = await worker.run_once(now)
    assert result["sent"] == 1
    assert [call.occurrence_id for call in sender.calls] == [occurrence_id]

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
