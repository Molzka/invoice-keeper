import asyncio
import json
from contextlib import contextmanager
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select

from app.core.security import verify_password
from app.models import AuditEvent, PaymentOccurrence, RecurringPayment, User, UserSession
from app.services.payments import today_in_timezone

from .conftest import PASSWORD

pytestmark = pytest.mark.asyncio
NEW_PASSWORD = "new-audit-password-456"


async def events(app):
    async with app.state.database.session_factory() as db:
        return list(
            await db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at, AuditEvent.id))
        )


async def create_payment(client, token, today):
    due = today - timedelta(days=4)
    response = await client.post(
        "/api/v1/recurring-payments",
        json={
            "title": "Audit office",
            "amount": "1250.00",
            "currency": "RUB",
            "first_due_date": due.isoformat(),
            "periodicity": "monthly",
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201, response.text
    payment = response.json()
    response = await client.get(
        "/api/v1/payment-occurrences",
        params={"recurring_payment_id": payment["id"], "date_to": due.isoformat()},
    )
    assert response.status_code == 200, response.text
    return payment, response.json()["items"][0]


@contextmanager
def failing_audit_insert(app):
    engine = app.state.database.engine.sync_engine

    def reject_insert(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT_EVENTS"):
            raise RuntimeError("Simulated audit storage failure")

    event.listen(engine, "before_cursor_execute", reject_insert)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", reject_insert)


async def test_payment_audit_records_actual_transitions_with_period_and_actor(
    app, client, create_user, login
):
    admin = await create_user()
    ordinary = await create_user("ordinary", role="user")
    auth = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    payment, period = await create_payment(client, auth["csrf_token"], today)
    user_auth = await login(client, "ordinary")
    headers = {"X-CSRF-Token": user_auth["csrf_token"]}
    path = f"/api/v1/payment-occurrences/{period['id']}"
    for payload in (
        {"status": "paid", "paid_on": today.isoformat()},
        {"status": "paid", "paid_on": period["due_date"]},
        {"status": "paid", "paid_on": period["due_date"]},
        {"status": "unpaid", "paid_on": None},
        {"status": "unpaid", "paid_on": None},
    ):
        response = await client.patch(path, json=payload, headers=headers)
        assert response.status_code == 200, response.text
    admin_auth = await login(client)
    for _ in range(2):
        response = await client.delete(
            f"/api/v1/recurring-payments/{payment['id']}",
            headers={"X-CSRF-Token": admin_auth["csrf_token"]},
        )
        assert response.status_code == 204
    recorded = await events(app)
    assert [item.action for item in recorded] == [
        "payment.created",
        "payment.paid",
        "payment.date_changed",
        "payment.unpaid",
        "payment.stopped",
    ]
    assert recorded[0].actor_id == recorded[-1].actor_id == admin.id
    for item in recorded:
        assert str(item.entity_id) == payment["id"]
        assert item.entity_type == "payment" and item.entity_title == "Audit office"
    for item in recorded[1:4]:
        assert item.actor_id == ordinary.id and item.actor_username == "ordinary"
        assert any(
            change["field"] == "due_date" and change["after"] == period["due_date"]
            for change in item.changes
        )
    corrected = {change["field"]: change for change in recorded[2].changes}
    assert corrected["paid_on"]["before"] == today.isoformat()
    assert corrected["paid_on"]["after"] == period["due_date"]
    assert "status" not in corrected


async def test_user_audit_retains_snapshots_and_never_records_credentials(
    app, client, create_user, login
):
    admin = await create_user()
    auth = await login(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    created = await client.post(
        "/api/v1/users", json={"username": "original", "password": PASSWORD}, headers=headers
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    path = f"/api/v1/users/{user_id}"
    for values in ({"username": "renamed"}, {"username": "renamed"}, {"password": NEW_PASSWORD}):
        response = await client.patch(path, json=values, headers=headers)
        assert response.status_code == 200, response.text
    assert (await client.delete(path, headers=headers)).status_code == 204
    response = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    recorded = await events(app)
    assert [item.action for item in recorded] == [
        "user.created",
        "user.updated",
        "user.updated",
        "user.deleted",
        "password.changed",
    ]
    assert recorded[0].entity_title == "original"
    assert [item.entity_title for item in recorded[1:4]] == ["renamed"] * 3
    assert all(str(item.entity_id) == user_id for item in recorded[:4])
    assert all(item.actor_id == admin.id and item.actor_username == "admin" for item in recorded)
    assert recorded[2].changes == recorded[4].changes == []
    assert recorded[4].entity_type == "account"
    details = json.dumps([item.changes for item in recorded])
    for secret in (PASSWORD, NEW_PASSWORD, "password", "token", "cookie", "csrf", "$argon2"):
        assert secret not in details.lower()
    async with app.state.database.session_factory() as db:
        assert await db.get(User, user_id) is None


async def test_payment_audit_survives_actor_rename_and_deletion(app, client, create_user, login):
    await create_user()
    ordinary = await create_user("original_actor", role="user")
    auth = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    _, period = await create_payment(client, auth["csrf_token"], today)
    user_auth = await login(client, "original_actor")
    response = await client.patch(
        f"/api/v1/payment-occurrences/{period['id']}",
        json={"status": "paid", "paid_on": today.isoformat()},
        headers={"X-CSRF-Token": user_auth["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    admin_auth = await login(client)
    headers = {"X-CSRF-Token": admin_auth["csrf_token"]}
    assert (
        await client.patch(
            f"/api/v1/users/{ordinary.id}", json={"username": "new_actor"}, headers=headers
        )
    ).status_code == 200
    assert (await client.delete(f"/api/v1/users/{ordinary.id}", headers=headers)).status_code == 204
    paid = next(item for item in await events(app) if item.action == "payment.paid")
    assert paid.actor_id == ordinary.id and paid.actor_username == "original_actor"


async def test_same_credentials_are_noop_preserving_password_hash_and_sessions(
    app, client, create_user, login
):
    await create_user()
    ordinary = await create_user("ordinary", role="user")
    auth = await login(client)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        ordinary_auth = await login(other, "ordinary")
        async with app.state.database.session_factory() as db:
            before_hash = (await db.get(User, ordinary.id)).password_hash
            before_sessions = set(
                await db.scalars(select(UserSession.id).where(UserSession.user_id == ordinary.id))
            )
        response = await client.patch(
            f"/api/v1/users/{ordinary.id}",
            json={"username": "ordinary", "password": PASSWORD},
            headers={"X-CSRF-Token": auth["csrf_token"]},
        )
        assert response.status_code == 200, response.text
        assert (await other.get("/api/v1/auth/me")).json() == ordinary_auth
        assert await events(app) == []
        async with app.state.database.session_factory() as db:
            assert (await db.get(User, ordinary.id)).password_hash == before_hash
            assert (
                set(
                    await db.scalars(
                        select(UserSession.id).where(UserSession.user_id == ordinary.id)
                    )
                )
                == before_sessions
            )


async def test_rejected_requests_and_username_conflicts_do_not_create_events(
    app, client, create_user, login
):
    await create_user()
    ordinary = await create_user("ordinary", role="user")
    auth = await login(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    for method, path, payload, status in (
        ("POST", "/api/v1/users", {"username": "ordinary", "password": PASSWORD}, 409),
        ("PATCH", f"/api/v1/users/{ordinary.id}", {"username": "admin"}, 409),
        ("PATCH", f"/api/v1/users/{ordinary.id}", {"username": "ordinary"}, 200),
        (
            "POST",
            "/api/v1/auth/change-password",
            {"current_password": "incorrect", "new_password": NEW_PASSWORD},
            422,
        ),
    ):
        response = await client.request(method, path, json=payload, headers=headers)
        assert response.status_code == status, response.text
    assert await events(app) == []


@pytest.mark.parametrize("operation", ["create", "stop", "pay"])
async def test_audit_insert_failure_rolls_back_payment_mutation(
    app, client, create_user, login, operation
):
    await create_user()
    auth = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    payment, period = await create_payment(client, auth["csrf_token"], today)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    with (
        failing_audit_insert(app),
        pytest.raises(RuntimeError, match="Simulated audit storage failure"),
    ):
        if operation == "create":
            await create_payment(client, auth["csrf_token"], today)
        elif operation == "stop":
            await client.delete(f"/api/v1/recurring-payments/{payment['id']}", headers=headers)
        else:
            await client.patch(
                f"/api/v1/payment-occurrences/{period['id']}",
                json={"status": "paid", "paid_on": today.isoformat()},
                headers=headers,
            )
    assert len(await events(app)) == 1
    async with app.state.database.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(RecurringPayment)) == 1
        assert (await db.get(RecurringPayment, payment["id"])).is_active
        current = await db.get(PaymentOccurrence, period["id"])
        assert current.status == "unpaid" and current.paid_on is None


@pytest.mark.parametrize("operation", ["create", "update", "delete", "change-password"])
async def test_audit_insert_failure_rolls_back_user_password_and_sessions(
    app, client, create_user, login, operation
):
    admin = await create_user()
    ordinary = await create_user("ordinary", role="user")
    auth = await login(client)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        await login(other, "ordinary")
        with (
            failing_audit_insert(app),
            pytest.raises(RuntimeError, match="Simulated audit storage failure"),
        ):
            headers = {"X-CSRF-Token": auth["csrf_token"]}
            if operation == "create":
                await client.post(
                    "/api/v1/users",
                    json={"username": "newuser", "password": PASSWORD},
                    headers=headers,
                )
            elif operation == "update":
                await client.patch(
                    f"/api/v1/users/{ordinary.id}",
                    json={"username": "renamed", "password": NEW_PASSWORD},
                    headers=headers,
                )
            elif operation == "delete":
                await client.delete(f"/api/v1/users/{ordinary.id}", headers=headers)
            else:
                await client.post(
                    "/api/v1/auth/change-password",
                    json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                    headers=headers,
                )
        assert (await client.get("/api/v1/auth/me")).json() == auth
        assert (await other.get("/api/v1/auth/me")).status_code == 200
    assert await events(app) == []
    async with app.state.database.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 2
        for user_id in (admin.id, ordinary.id):
            stored = await db.get(User, user_id)
            assert await verify_password(PASSWORD, stored.password_hash)
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(UserSession)
                    .where(UserSession.user_id == user_id)
                )
                == 1
            )
        assert (await db.get(User, ordinary.id)).username == "ordinary"


async def test_concurrent_identical_payment_updates_create_one_event(
    app, client, create_user, login
):
    await create_user()
    auth = await login(client)
    today = today_in_timezone(app.state.settings.app_timezone)
    _, period = await create_payment(client, auth["csrf_token"], today)
    responses = await asyncio.gather(
        *[
            client.patch(
                f"/api/v1/payment-occurrences/{period['id']}",
                json={"status": "paid", "paid_on": today.isoformat()},
                headers={"X-CSRF-Token": auth["csrf_token"]},
            )
            for _ in range(2)
        ]
    )
    assert all(response.status_code == 200 for response in responses)
    assert [item.action for item in await events(app)] == ["payment.created", "payment.paid"]
