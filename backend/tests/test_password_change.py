import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, update

from app.core.security import verify_password
from app.models import LoginRateLimit, User, UserSession
from app.services import auth as auth_service

from .conftest import PASSWORD
from .test_auth import assert_error

pytestmark = pytest.mark.asyncio
PATH = "/api/v1/auth/change-password"
NEW_PASSWORD = "changed-password-456"


def browser(app, token=None):
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
        cookies={app.state.settings.session_cookie_name: token} if token else None,
    )


async def change(client, csrf_token, **values):
    return await client.post(
        PATH,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD, **values},
        headers={"X-CSRF-Token": csrf_token},
    )


@pytest.mark.parametrize("role", ["admin", "user"])
async def test_change_password_respects_role_and_preserves_session_contract(
    app, client, create_user, login, role
):
    app.state.settings.app_timezone = "Asia/Tokyo"
    user = await create_user("owner", role=role)
    await create_user("another", role="user")
    auth = await login(client, "owner")
    cookie_name = app.state.settings.session_cookie_name
    old_token = client.cookies[cookie_name]
    async with browser(app) as other_session, browser(app) as unrelated:
        await login(other_session, "owner")
        await login(unrelated, "another")
        async with app.state.database.session_factory() as db:
            original_hash = (await db.get(User, user.id)).password_hash
            current = await db.scalar(
                select(UserSession).where(
                    UserSession.token_hash == hashlib.sha256(old_token.encode()).hexdigest()
                )
            )
            expires_at = current.expires_at

        response = await change(client, auth["csrf_token"])
        if role == "admin":
            assert_error(response, 403, "ADMIN_ACCOUNT_PROTECTED")
            assert "set-cookie" not in response.headers
            assert client.cookies[cookie_name] == old_token
            assert (await client.get("/api/v1/auth/me")).json() == auth
            assert (await other_session.get("/api/v1/auth/me")).status_code == 200
            assert (await unrelated.get("/api/v1/auth/me")).status_code == 200
            async with app.state.database.session_factory() as db:
                assert (await db.get(User, user.id)).password_hash == original_hash
                sessions = (
                    await db.scalars(select(UserSession).where(UserSession.user_id == user.id))
                ).all()
                assert len(sessions) == 2
                assert any(
                    session.token_hash == hashlib.sha256(old_token.encode()).hexdigest()
                    and session.expires_at == expires_at
                    for session in sessions
                )
            await login(other_session, "owner", PASSWORD)
            return
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["user"] == auth["user"]
        assert changed["csrf_token"] != auth["csrf_token"]
        assert changed["timezone"] == "Asia/Tokyo"
        assert response.headers["cache-control"] == "no-store"
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
        assert client.cookies[cookie_name] != old_token
        assert (await client.get("/api/v1/auth/me")).json() == changed
        assert_error(await other_session.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")
        assert (await unrelated.get("/api/v1/auth/me")).status_code == 200
        async with browser(app, old_token) as replay:
            assert_error(await replay.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")
        async with app.state.database.session_factory() as db:
            stored_user = await db.get(User, user.id)
            assert stored_user.password_hash != original_hash
            assert await verify_password(NEW_PASSWORD, stored_user.password_hash)
            sessions = (
                await db.scalars(select(UserSession).where(UserSession.user_id == user.id))
            ).all()
            assert len(sessions) == 1 and sessions[0].expires_at == expires_at
        assert_error(
            await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]}),
            403,
            "CSRF_FAILED",
        )
        assert_error(
            await other_session.post(
                "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
            ),
            401,
            "INVALID_CREDENTIALS",
        )
        await login(other_session, "owner", NEW_PASSWORD)


@pytest.mark.parametrize("new_password", ["12345678", "x" * 128, "  новый пароль 🔐  "])
async def test_password_limits_and_whitespace_are_preserved(
    app, client, create_user, login, new_password
):
    await create_user(role="user")
    auth = await login(client)
    response = await change(client, auth["csrf_token"], new_password=new_password)
    assert response.status_code == 200, response.text
    async with browser(app) as fresh:
        await login(fresh, "admin", new_password)


@pytest.mark.parametrize(
    "values,code,field",
    [
        ({"current_password": "incorrect"}, "CURRENT_PASSWORD_INVALID", "current_password"),
        ({"new_password": PASSWORD}, "NEW_PASSWORD_UNCHANGED", "new_password"),
    ],
)
async def test_password_errors_preserve_password_and_sessions(
    app, client, create_user, login, values, code, field
):
    user = await create_user(role="user")
    auth = await login(client)
    token = client.cookies[app.state.settings.session_cookie_name]
    async with app.state.database.session_factory() as db:
        original_hash = (await db.get(User, user.id)).password_hash
    response = await change(client, auth["csrf_token"], **values)
    assert_error(response, 422, code)
    assert response.json()["error"]["details"][0]["field"] == field
    assert "set-cookie" not in response.headers
    assert PASSWORD not in response.text and NEW_PASSWORD not in response.text
    assert client.cookies[app.state.settings.session_cookie_name] == token
    assert (await client.get("/api/v1/auth/me")).json() == auth
    async with app.state.database.session_factory() as db:
        assert (await db.get(User, user.id)).password_hash == original_hash


@pytest.mark.parametrize(
    "payload,field,code",
    [
        ({"new_password": NEW_PASSWORD}, "current_password", "REQUIRED"),
        ({"current_password": PASSWORD}, "new_password", "REQUIRED"),
        (
            {"current_password": None, "new_password": NEW_PASSWORD},
            "current_password",
            "INVALID_TYPE",
        ),
        ({"current_password": "", "new_password": NEW_PASSWORD}, "current_password", "TOO_SHORT"),
        (
            {"current_password": "x" * 129, "new_password": NEW_PASSWORD},
            "current_password",
            "TOO_LONG",
        ),
        ({"current_password": PASSWORD, "new_password": None}, "new_password", "INVALID_TYPE"),
        ({"current_password": PASSWORD, "new_password": 12345678}, "new_password", "INVALID_TYPE"),
        ({"current_password": PASSWORD, "new_password": "short"}, "new_password", "TOO_SHORT"),
        ({"current_password": PASSWORD, "new_password": "x" * 129}, "new_password", "TOO_LONG"),
        (
            {"current_password": PASSWORD, "new_password": NEW_PASSWORD, "user_id": "other"},
            "user_id",
            "UNKNOWN_FIELD",
        ),
    ],
)
async def test_password_request_validation_never_echoes_input(
    client, create_user, login, payload, field, code
):
    await create_user(role="user")
    auth = await login(client)
    response = await client.post(PATH, json=payload, headers={"X-CSRF-Token": auth["csrf_token"]})
    assert_error(response, 422, "VALIDATION_ERROR")
    assert {"field": field, "code": code} in [
        {"field": detail["field"], "code": detail["code"]}
        for detail in response.json()["error"]["details"]
    ]
    assert PASSWORD not in response.text and NEW_PASSWORD not in response.text
    assert '"input"' not in response.text
    assert (await client.get("/api/v1/auth/me")).json() == auth


async def test_password_change_requires_session_csrf_origin_and_json(client, create_user, login):
    assert_error(await change(client, "not-authenticated"), 401, "AUTH_REQUIRED")
    await create_user(role="user")
    auth = await login(client)
    for token in ("", "incorrect"):
        assert_error(await change(client, token), 403, "CSRF_FAILED")
    for origin in (None, "https://foreign.example"):
        response = await client.post(
            PATH,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers={"X-CSRF-Token": auth["csrf_token"], "Origin": origin or "null"},
        )
        assert_error(response, 403, "ORIGIN_NOT_ALLOWED")
    del client.headers["Origin"]
    assert_error(await change(client, auth["csrf_token"]), 403, "ORIGIN_NOT_ALLOWED")
    client.headers["Origin"] = "http://testserver"
    response = await client.post(
        PATH,
        content="{",
        headers={"Content-Type": "application/json", "X-CSRF-Token": auth["csrf_token"]},
    )
    assert_error(response, 400, "INVALID_JSON")
    assert_error(
        await client.post(
            PATH, content="current_password=test", headers={"X-CSRF-Token": auth["csrf_token"]}
        ),
        415,
        "UNSUPPORTED_MEDIA_TYPE",
    )
    response = await client.post(
        PATH + "?user_id=other",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"X-CSRF-Token": auth["csrf_token"]},
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert response.json()["error"]["details"][0]["code"] == "UNKNOWN_QUERY_PARAMETER"
    assert (await client.get("/api/v1/auth/me")).json() == auth


async def test_password_change_limit_is_shared_across_sessions_and_separate_from_login(
    app, client, create_user, login
):
    user = await create_user(role="user")
    app.state.settings.password_change_rate_limit_attempts = 2
    app.state.settings.password_change_rate_limit_window_seconds = 60
    auth = await login(client)
    async with browser(app) as other:
        second_auth = await login(other)
        for api, token in [(client, auth["csrf_token"]), (other, second_auth["csrf_token"])]:
            assert_error(
                await change(api, token, current_password="incorrect"),
                422,
                "CURRENT_PASSWORD_INVALID",
            )
        response = await change(client, auth["csrf_token"])
        assert_error(response, 429, "PASSWORD_CHANGE_RATE_LIMITED")
        assert int(response.headers["retry-after"]) > 0
        await login(other)  # A blocked password-change bucket must not block login.
        async with app.state.database.session_factory() as db:
            key = hashlib.sha256(f"password-change:{user.id}".encode()).hexdigest()
            await db.execute(
                update(LoginRateLimit)
                .where(LoginRateLimit.key == key)
                .values(window_started_at=datetime.now(UTC) - timedelta(minutes=2))
            )
            await db.commit()
        assert (await change(client, auth["csrf_token"])).status_code == 200


async def test_concurrent_password_changes_cannot_restore_a_revoked_session(
    app, client, create_user, login
):
    user = await create_user(role="user")
    auth = await login(client)
    async with browser(app) as other:
        second_auth = await login(other)
        responses = await asyncio.gather(
            change(client, auth["csrf_token"]),
            change(other, second_auth["csrf_token"], new_password="another-new-password"),
        )
    assert sorted(response.status_code for response in responses) == [200, 401]
    winning_password = NEW_PASSWORD if responses[0].status_code == 200 else "another-new-password"
    async with app.state.database.session_factory() as db:
        assert await verify_password(winning_password, (await db.get(User, user.id)).password_hash)
        assert (
            await db.scalar(
                select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
            )
            == 1
        )


@pytest.mark.parametrize("account_change", ["logout", "promote_to_admin"])
async def test_account_changed_during_password_hashing_cannot_change_password(
    app, client, create_user, login, monkeypatch, account_change
):
    user = await create_user(role="user")
    auth = await login(client)
    started, release = asyncio.Event(), asyncio.Event()
    original_hash = auth_service.hash_password

    async def paused_hash(password):
        result = await original_hash(password)
        started.set()
        await release.wait()
        return result

    monkeypatch.setattr(auth_service, "hash_password", paused_hash)
    changing = asyncio.create_task(change(client, auth["csrf_token"]))
    try:
        await asyncio.wait_for(started.wait(), 5)
        if account_change == "logout":
            assert (
                await client.post(
                    "/api/v1/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]}
                )
            ).status_code == 204
        else:
            async with app.state.database.session_factory() as db:
                await db.execute(update(User).where(User.id == user.id).values(role="admin"))
                await db.commit()
    finally:
        release.set()
        response = await changing
    if account_change == "logout":
        assert_error(response, 401, "AUTH_REQUIRED")
    else:
        assert_error(response, 403, "ADMIN_ACCOUNT_PROTECTED")
    async with app.state.database.session_factory() as db:
        assert await verify_password(PASSWORD, (await db.get(User, user.id)).password_hash)
        expected_sessions = 0 if account_change == "logout" else 1
        assert await db.scalar(select(func.count()).select_from(UserSession)) == expected_sessions


async def test_failed_commit_rolls_back_password_and_session_revocation(
    app, client, create_user, login, monkeypatch
):
    user = await create_user(role="user")
    auth = await login(client)

    def fail_commit(connection):
        raise RuntimeError("Simulated password-change commit failure")

    original_hash = auth_service.hash_password

    async def hash_then_fail_commit(password):
        result = await original_hash(password)
        event.listen(app.state.database.engine.sync_engine, "commit", fail_commit, once=True)
        return result

    monkeypatch.setattr(auth_service, "hash_password", hash_then_fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Simulated password-change commit failure"):
            await change(client, auth["csrf_token"])
    finally:
        event.remove(app.state.database.engine.sync_engine, "commit", fail_commit)
    async with app.state.database.session_factory() as db:
        assert await verify_password(PASSWORD, (await db.get(User, user.id)).password_hash)
    assert (await client.get("/api/v1/auth/me")).json() == auth
