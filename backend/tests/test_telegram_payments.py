import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select, text

from app.main import create_app
from app.models import AuditEvent, PaymentOccurrence, User

from .conftest import PASSWORD
from .test_audit_mutations import failing_audit_insert

pytestmark = pytest.mark.asyncio
WEB = "/api/v1/auth/telegram-payments"
INTERNAL = "/internal/v1/telegram-payments"
TG_ID = 123456789
CHAT_ID = -1001234567890
BRIDGE = {"Authorization": "Bearer " + "test-bridge-" * 4}


async def prepare_account(client, app, create_user, login):
    settings = app.state.settings
    settings.bot_internal_token = SecretStr("test-bridge-" * 4)
    settings.bot_username = "invoice_test_bot"
    settings.chat_id = str(CHAT_ID)
    settings.mfa_encryption_key = None
    await create_user()
    member = await create_user("member", role="user")
    admin = await login(client)
    created = await client.post(
        "/api/v1/one-time-payments",
        json={
            "title": "Telegram rent",
            "amount": "123.45",
            "currency": "EUR",
            "due_date": "2026-01-01",
        },
        headers={"X-CSRF-Token": admin["csrf_token"]},
    )
    assert created.status_code == 201
    auth = await login(client, "member")
    return member, created.json(), {"X-CSRF-Token": auth["csrf_token"]}


async def link_account(client, headers):
    assert (
        await client.post(
            "/api/v1/auth/security/reauth", json={"password": PASSWORD}, headers=headers
        )
    ).status_code == 200
    setup = await client.post(WEB + "/setup", json={}, headers=headers)
    assert setup.status_code == 200, setup.text
    setup = setup.json()
    token = setup["link"].split("start=paylink_")[1]
    payload = {
        "token": token,
        "telegram_id": TG_ID,
        "chat_id": TG_ID,
        "username": "member_tg",
        "display_name": "Team member",
    }
    assert (await client.post(INTERNAL + "/claim", json=payload)).status_code == 403
    assert (
        await client.post(INTERNAL + "/claim", json={**payload, "chat_id": CHAT_ID}, headers=BRIDGE)
    ).status_code == 400
    assert (await client.post(INTERNAL + "/claim", json=payload, headers=BRIDGE)).status_code == 200
    assert (await client.post(INTERNAL + "/claim", json=payload, headers=BRIDGE)).status_code == 409
    state = await client.get(WEB + "/setup/" + setup["setup_id"])
    assert state.json()["account"]["id"] == str(TG_ID)
    assert (
        await client.post(
            WEB + "/confirm",
            json={"setup_id": setup["setup_id"], "telegram_id": str(TG_ID)},
            headers=headers,
        )
    ).status_code == 200
    assert (await client.get("/api/v1/auth/security")).json()["mfa_enabled"] is False


async def prepare_payment(client, item, **overrides):
    return await client.post(
        INTERNAL + "/prepare",
        json={
            "telegram_id": TG_ID,
            "chat_id": CHAT_ID,
            "occurrence_id": item["id"],
            **overrides,
        },
        headers=BRIDGE,
    )


async def test_binding_and_payment_enforce_identity_and_replays_never_repay(
    client, app, create_user, login
):
    member, item, headers = await prepare_account(client, app, create_user, login)
    assert (await prepare_payment(client, item)).status_code == 403
    assert (await client.post(WEB + "/setup", json={}, headers=headers)).status_code == 409
    await link_account(client, headers)
    assert (await prepare_payment(client, item, user_id=str(member.id))).status_code == 422
    assert (await prepare_payment(client, item, chat_id=777)).status_code == 403
    prepared = await prepare_payment(client, item)
    assert prepared.status_code == 200, prepared.text
    confirmation = prepared.json()
    body = {"telegram_id": TG_ID, "chat_id": CHAT_ID, "token": confirmation["token"]}
    assert (
        await client.post(
            INTERNAL + "/confirm", json={**body, "telegram_id": TG_ID + 1}, headers=BRIDGE
        )
    ).status_code == 403
    restarted = create_app(app.state.settings)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://testserver"
        ) as second_process:
            responses = await asyncio.gather(
                client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE),
                second_process.post(INTERNAL + "/confirm", json=body, headers=BRIDGE),
            )
    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()["outcome"] for response in responses) == [
        "already_processed",
        "paid",
    ]
    assert responses[0].json()["payment"]["paid_on"] == confirmation["paid_on"]
    async with app.state.database.session_factory() as db:
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "payment.paid"))
        )
        assert len(events) == 1 and events[0].actor_id == member.id
    assert (
        await client.patch(
            "/api/v1/payment-occurrences/" + item["id"],
            json={"status": "unpaid", "paid_on": None},
            headers=headers,
        )
    ).status_code == 200
    replay = await client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE)
    assert replay.json()["outcome"] == "already_processed"
    assert replay.json()["payment"]["status"] == "unpaid"
    app.state.settings.bot_username = None
    unavailable = (await client.get(WEB)).json()
    assert unavailable["available"] is False and unavailable["account"]["id"] == str(TG_ID)
    assert (
        await client.post(
            "/api/v1/auth/security/reauth", json={"password": PASSWORD}, headers=headers
        )
    ).status_code == 200
    assert (await client.delete(WEB, headers=headers)).status_code == 204
    assert (await prepare_payment(client, item)).status_code == 403


async def test_confirmation_rejects_changed_cancelled_expired_or_revoked_access(
    client, app, create_user, login
):
    from app.models.telegram_payments import TelegramPaymentConfirmation

    member, item, headers = await prepare_account(client, app, create_user, login)
    await link_account(client, headers)
    prepared = (await prepare_payment(client, item)).json()
    body = {"telegram_id": TG_ID, "chat_id": CHAT_ID, "token": prepared["token"]}
    async with app.state.database.session_factory() as db:
        period = await db.get(PaymentOccurrence, item["id"])
        period.currency = "USD"
        await db.commit()
    assert (await client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE)).status_code == 409
    async with app.state.database.session_factory() as db:
        period = await db.get(PaymentOccurrence, item["id"])
        period.currency = "EUR"
        period.is_cancelled = True
        await db.commit()
    assert (await client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE)).status_code == 409
    async with app.state.database.session_factory() as db:
        (await db.get(PaymentOccurrence, item["id"])).is_cancelled = False
        row = await db.scalar(select(TelegramPaymentConfirmation))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    assert (await client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE)).status_code == 409
    prepared = (await prepare_payment(client, item)).json()
    async with app.state.database.session_factory() as db:
        (await db.get(User, member.id)).security_version += 1
        await db.commit()
    assert (
        await client.post(
            INTERNAL + "/confirm", json={**body, "token": prepared["token"]}, headers=BRIDGE
        )
    ).status_code == 409
    prepared = (await prepare_payment(client, item)).json()
    async with app.state.database.session_factory() as db:
        (await db.get(User, member.id)).is_active = False
        await db.commit()
    assert (
        await client.post(
            INTERNAL + "/confirm", json={**body, "token": prepared["token"]}, headers=BRIDGE
        )
    ).status_code == 403


async def test_admin_uses_server_configuration_and_cannot_link_through_panel(
    client, app, create_user, login
):
    _, item, _ = await prepare_account(client, app, create_user, login)
    app.state.settings.admin_username = "admin"
    app.state.settings.admin_telegram_id = TG_ID
    auth = await login(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    assert (await client.post(WEB + "/setup", json={}, headers=headers)).status_code == 403
    assert (await client.delete(WEB, headers=headers)).status_code == 403
    prepared = (await prepare_payment(client, item)).json()
    result = await client.post(
        INTERNAL + "/confirm",
        json={"token": prepared["token"], "telegram_id": TG_ID, "chat_id": CHAT_ID},
        headers=BRIDGE,
    )
    assert result.status_code == 200 and result.json()["outcome"] == "paid"
    async with app.state.database.session_factory() as db:
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "payment.paid"))
        assert event.actor_username == "admin"


async def test_link_is_browser_bound_and_cannot_take_another_users_telegram(
    client, app, create_user, login
):
    _, item, headers = await prepare_account(client, app, create_user, login)
    await link_account(client, headers)
    await client.post("/api/v1/auth/security/reauth", json={"password": PASSWORD}, headers=headers)
    own_setup = (await client.post(WEB + "/setup", json={}, headers=headers)).json()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as another_browser:
        await login(another_browser, "member")
        assert (
            await another_browser.get(WEB + "/setup/" + own_setup["setup_id"])
        ).status_code == 409
    assert (await client.get(WEB + "/setup/" + own_setup["setup_id"])).status_code == 200
    await create_user("other", role="user")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        auth = await login(other, "other")
        other_headers = {"X-CSRF-Token": auth["csrf_token"]}
        await other.post(
            "/api/v1/auth/security/reauth", json={"password": PASSWORD}, headers=other_headers
        )
        setup = (await other.post(WEB + "/setup", json={}, headers=other_headers)).json()
        token = setup["link"].split("start=paylink_")[1]
        assert (await client.get(WEB + "/setup/" + setup["setup_id"])).status_code == 409
        assert (
            await other.post(
                INTERNAL + "/claim",
                json={
                    "token": token,
                    "telegram_id": TG_ID,
                    "chat_id": TG_ID,
                    "display_name": "Other",
                },
                headers=BRIDGE,
            )
        ).status_code == 200
        conflict = await other.post(
            WEB + "/confirm",
            json={"setup_id": setup["setup_id"], "telegram_id": str(TG_ID)},
            headers=other_headers,
        )
        assert (
            conflict.status_code == 409
            and conflict.json()["error"]["code"] == "TELEGRAM_ALREADY_LINKED"
        )
        assert (await other.get(WEB)).json()["account"] is None
    assert (await prepare_payment(client, item)).status_code == 200


async def test_payment_confirmation_and_audit_are_atomic_and_keep_the_shown_date(
    client, app, create_user, login, monkeypatch
):
    from app.models.telegram_payments import TelegramPaymentConfirmation
    from app.services import telegram_payments

    _, item, headers = await prepare_account(client, app, create_user, login)
    await link_account(client, headers)
    prepared = (await prepare_payment(client, item)).json()
    body = {"token": prepared["token"], "telegram_id": TG_ID, "chat_id": CHAT_ID}
    with failing_audit_insert(app), pytest.raises(RuntimeError, match="audit storage failure"):
        await client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE)
    async with app.state.database.session_factory() as db:
        assert (await db.get(PaymentOccurrence, item["id"])).status == "unpaid"
        assert (await db.scalar(select(TelegramPaymentConfirmation))).state == "pending"
    today = telegram_payments.today_in_timezone(app.state.settings.app_timezone)
    monkeypatch.setattr(
        telegram_payments, "today_in_timezone", lambda _zone: today + timedelta(days=1)
    )
    response = await client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE)
    assert (
        response.status_code == 200 and response.json()["payment"]["paid_on"] == prepared["paid_on"]
    )


async def test_cancel_and_already_paid_never_change_a_previous_payment_date(
    client, app, create_user, login
):
    _, item, headers = await prepare_account(client, app, create_user, login)
    await link_account(client, headers)
    prepared = (await prepare_payment(client, item)).json()
    body = {"token": prepared["token"], "telegram_id": TG_ID, "chat_id": CHAT_ID}
    assert (await client.post(INTERNAL + "/cancel", json=body, headers=BRIDGE)).status_code == 200
    assert (await client.post(INTERNAL + "/confirm", json=body, headers=BRIDGE)).status_code == 409
    prepared = (await prepare_payment(client, item)).json()
    assert (
        await client.patch(
            "/api/v1/payment-occurrences/" + item["id"],
            json={"status": "paid", "paid_on": item["due_date"]},
            headers=headers,
        )
    ).status_code == 200
    response = await client.post(
        INTERNAL + "/confirm", json={**body, "token": prepared["token"]}, headers=BRIDGE
    )
    assert response.json()["outcome"] == "already_paid"
    assert response.json()["payment"]["paid_on"] == item["due_date"]


async def test_admin_configuration_cannot_silently_take_over_an_existing_binding(
    client, app, create_user, login
):
    _, item, headers = await prepare_account(client, app, create_user, login)
    await link_account(client, headers)
    app.state.settings.admin_username = "admin"
    app.state.settings.admin_telegram_id = TG_ID
    response = await prepare_payment(client, item)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TELEGRAM_ID_CONFLICT"


async def test_waiting_prepare_rechecks_a_binding_removed_under_the_user_lock(
    client, app, create_user, login
):
    from app.models import TelegramPaymentAccount

    member, item, headers = await prepare_account(client, app, create_user, login)
    await link_account(client, headers)
    async with app.state.database.session_factory() as db:
        await db.scalar(select(User).where(User.id == member.id).with_for_update())
        request = asyncio.create_task(prepare_payment(client, item))
        try:
            async with asyncio.timeout(10):
                while True:
                    async with app.state.database.session_factory() as observer:
                        waiting = await observer.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname = current_database() "
                                "AND wait_event_type = 'Lock' AND query LIKE '%JOIN telegram_payment_accounts%' "
                                "AND query LIKE '%FOR UPDATE%')"
                            )
                        )
                    if waiting:
                        break
                    await asyncio.sleep(0.01)
            await db.execute(
                delete(TelegramPaymentAccount).where(TelegramPaymentAccount.user_id == member.id)
            )
            await db.commit()
            assert (await request).status_code == 403
        finally:
            await db.rollback()
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
