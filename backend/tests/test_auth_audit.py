import json

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.mfa_crypto import encrypt_secret, recovery_digest
from app.models import AuditEvent, UserSession
from app.models.mfa import MfaRecoveryCode, UserMfa

from .conftest import PASSWORD
from .test_audit_mutations import failing_audit_insert

pytestmark = pytest.mark.asyncio


async def auth_events(app):
    async with app.state.database.session_factory() as db:
        rows = await db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at, AuditEvent.id))
        return [
            row
            for row in rows
            if row.action in {"account.login", "account.login_failed", "account.logout"}
        ]


async def test_auth_journal_records_success_failure_and_logout_without_secrets(
    app, client, create_user, login
):
    admin = await create_user()
    for username in ("missing_user", "admin"):
        response = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "wrong-private-password"}
        )
        assert response.status_code == 401
    auth = await login(client)
    result = await client.get("/api/v1/audit-events", params={"action": "account.login_failed"})
    assert result.status_code == 200
    items = result.json()["items"]
    assert result.json()["total"] == 2
    missing = next(row for row in items if row["actor"]["username"] == "missing_user")
    assert missing["actor"]["id"] is None and missing["entity"]["id"] is None
    assert (await client.post("/api/v1/auth/logout")).status_code == 403
    assert (
        await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]})
    ).status_code == 204
    assert (await client.get("/api/v1/audit-events")).status_code == 401
    events = await auth_events(app)
    assert [event.action for event in events] == [
        "account.login_failed",
        "account.login_failed",
        "account.login",
        "account.logout",
    ]
    assert all(event.actor_id == admin.id for event in events[1:])
    serialized = json.dumps(
        [
            {"actor": event.actor_username, "entity": event.entity_title, "changes": event.changes}
            for event in events
        ]
    )
    for secret in (PASSWORD, "wrong-private-password", auth["csrf_token"], "$argon2"):
        assert secret not in serialized


async def test_mfa_login_is_recorded_only_after_second_factor_and_failed_proofs_persist(
    app, client, create_user
):
    user = await create_user("member", role="user")
    settings = app.state.settings
    settings.mfa_encryption_key = SecretStr(Fernet.generate_key().decode())
    recovery = "12345678-ABCDEF12-12345678-ABCDEF12"
    async with app.state.database.session_factory() as db:
        db.add(UserMfa(user_id=user.id, totp_secret=encrypt_secret(settings, "JBSWY3DPEHPK3PXP")))
        db.add(MfaRecoveryCode(user_id=user.id, code_hash=recovery_digest(recovery)))
        await db.commit()
    pending = await client.post(
        "/api/v1/auth/login", json={"username": "member", "password": PASSWORD}
    )
    assert pending.json()["mfa_required"] is True
    assert await auth_events(app) == []
    assert (await client.get("/api/v1/payment-occurrences")).status_code == 401
    headers = {"X-CSRF-Token": pending.json()["csrf_token"]}
    assert (
        await client.post(
            "/api/v1/auth/mfa/verify", headers=headers, json={"method": "recovery", "code": "wrong"}
        )
    ).status_code == 422
    verified = await client.post(
        "/api/v1/auth/mfa/verify", headers=headers, json={"method": "recovery", "code": recovery}
    )
    assert verified.status_code == 200
    assert [event.action for event in await auth_events(app)] == [
        "account.login_failed",
        "account.login",
    ]
    assert (await client.get("/api/v1/audit-events")).status_code == 403


async def test_session_and_auth_journal_commit_together(app, client, create_user, login):
    await create_user()
    with failing_audit_insert(app), pytest.raises(RuntimeError, match="audit storage failure"):
        await client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    async with app.state.database.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(UserSession)) == 0
    assert await auth_events(app) == []
    auth = await login(client)
    with failing_audit_insert(app), pytest.raises(RuntimeError, match="audit storage failure"):
        await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]})
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert [event.action for event in await auth_events(app)] == ["account.login"]
