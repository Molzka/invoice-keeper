from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.models import LoginRateLimit, UserSession

from .conftest import PASSWORD

pytestmark = pytest.mark.asyncio


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert "details" in error


async def test_login_me_logout_and_revoked_token_replay(app, client, create_user, login):
    app.state.settings.app_timezone = "Asia/Tokyo"
    user = await create_user()
    authentication = await login(client)
    token = client.cookies[app.state.settings.session_cookie_name]
    assert authentication["user"]["id"] == str(user.id)
    assert authentication["csrf_token"]
    assert authentication["timezone"] == "Asia/Tokyo"
    assert "password" not in authentication["user"]
    assert "password_hash" not in authentication["user"]

    async with app.state.database.session_factory() as session:
        stored = (await session.scalars(select(UserSession))).one()
        assert stored.token_hash != token
        assert len(stored.token_hash) == 64
        assert stored.expires_at > datetime.now(UTC)

    current = await client.get("/api/v1/auth/me")
    assert current.status_code == 200
    assert current.json() == authentication

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": authentication["csrf_token"]},
    )
    assert logout.status_code == 204
    assert not logout.content
    assert "max-age=0" in logout.headers["set-cookie"].lower()
    assert_error(await client.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={app.state.settings.session_cookie_name: token},
    ) as replay_client:
        assert_error(await replay_client.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")


async def test_cookie_attributes_are_explicit(app, client, create_user):
    await create_user()
    payload = {"username": "admin", "password": PASSWORD}
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "max-age=3600" in cookie
    assert "; secure" not in cookie

    app.state.settings.session_cookie_secure = True
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    assert "; secure" in response.headers["set-cookie"].lower()


async def test_bad_unknown_and_inactive_credentials_have_same_public_error(client, create_user):
    await create_user()
    await create_user("disabled", is_active=False)
    attempts = [
        {"username": "admin", "password": "wrong-password-123"},
        {"username": "unknown", "password": PASSWORD},
        {"username": "disabled", "password": PASSWORD},
    ]
    responses = [await client.post("/api/v1/auth/login", json=body) for body in attempts]
    for response in responses:
        assert_error(response, 401, "INVALID_CREDENTIALS")
        assert "set-cookie" not in response.headers
    assert responses[0].json() == responses[1].json() == responses[2].json()


async def test_expired_and_unknown_sessions_are_rejected(app, client, create_user, login):
    await create_user()
    await login(client)
    async with app.state.database.session_factory() as session:
        await session.execute(
            update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert_error(await client.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")

    client.cookies.clear()
    client.cookies.set(app.state.settings.session_cookie_name, "unknown-session-token")
    assert_error(await client.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")


async def test_logout_requires_matching_csrf_token(client, create_user, login):
    await create_user()
    authentication = await login(client)
    assert_error(await client.post("/api/v1/auth/logout"), 403, "CSRF_FAILED")
    assert_error(
        await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "incorrect"}),
        403,
        "CSRF_FAILED",
    )
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert (
        await client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": authentication["csrf_token"]},
        )
    ).status_code == 204


async def test_foreign_origin_rejected_and_referer_cannot_replace_origin(
    client, create_user, login
):
    await create_user()
    assert_error(
        await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": PASSWORD},
            headers={"Origin": "https://foreign.example"},
        ),
        403,
        "ORIGIN_NOT_ALLOWED",
    )
    authentication = await login(client)
    assert_error(
        await client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://testserver.foreign.example",
                "X-CSRF-Token": authentication["csrf_token"],
            },
        ),
        403,
        "ORIGIN_NOT_ALLOWED",
    )
    del client.headers["Origin"]
    response = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Referer": "http://testserver/settings",
            "X-CSRF-Token": authentication["csrf_token"],
        },
    )
    assert_error(response, 403, "ORIGIN_NOT_ALLOWED")


async def test_username_rate_limit_blocks_correct_credentials_until_window_ends(
    app, client, create_user
):
    await create_user()
    app.state.settings.login_rate_limit_attempts = 2
    for _ in range(2):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password-123"},
        )
        assert_error(response, 401, "INVALID_CREDENTIALS")
    response = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    )
    assert_error(response, 429, "LOGIN_RATE_LIMITED")
    assert int(response.headers["retry-after"]) > 0

    async with app.state.database.session_factory() as session:
        await session.execute(
            update(LoginRateLimit).values(
                window_started_at=datetime.now(UTC) - timedelta(minutes=2)
            )
        )
        await session.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
    )
    assert response.status_code == 200


async def test_ip_rate_limit_covers_multiple_usernames(app, client):
    app.state.settings.login_rate_limit_ip_attempts = 3
    for index in range(3):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": f"unknown{index}", "password": PASSWORD},
            headers={"X-Forwarded-For": f"192.0.2.{index + 1}"},
        )
        assert_error(response, 401, "INVALID_CREDENTIALS")
    response = await client.post(
        "/api/v1/auth/login", json={"username": "another", "password": PASSWORD}
    )
    assert_error(response, 429, "LOGIN_RATE_LIMITED")
    assert int(response.headers["retry-after"]) > 0


async def test_validation_error_never_echoes_password(client):
    password = "secret!" * 20
    response = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": password}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert password not in response.text
    assert '"input"' not in response.text


async def test_short_wrong_password_uses_generic_credentials_error(client, create_user):
    await create_user()
    response = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert_error(response, 401, "INVALID_CREDENTIALS")


async def test_login_normalizes_username_and_rotates_previous_session(
    app, client, create_user, login
):
    await create_user()
    await login(client, " ADMIN ")
    old_token = client.cookies[app.state.settings.session_cookie_name]
    await login(client)
    assert client.cookies[app.state.settings.session_cookie_name] != old_token
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies={app.state.settings.session_cookie_name: old_token},
    ) as replay_client:
        assert_error(await replay_client.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")


async def test_blocked_ip_cannot_grow_username_buckets(app, client):
    app.state.settings.login_rate_limit_ip_attempts = 1
    first = await client.post(
        "/api/v1/auth/login", json={"username": "unknown", "password": PASSWORD}
    )
    assert_error(first, 401, "INVALID_CREDENTIALS")
    for index in range(5):
        response = await client.post(
            "/api/v1/auth/login", json={"username": f"unknown{index}", "password": PASSWORD}
        )
        assert_error(response, 429, "LOGIN_RATE_LIMITED")
    async with app.state.database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(LoginRateLimit)) == 2


async def test_csrf_token_from_other_session_does_not_authorize_logout(
    app, client, create_user, login
):
    await create_user()
    first = await login(client)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as second_client:
        second = await login(second_client)
        assert first["csrf_token"] != second["csrf_token"]
        assert_error(
            await second_client.post(
                "/api/v1/auth/logout", headers={"X-CSRF-Token": first["csrf_token"]}
            ),
            403,
            "CSRF_FAILED",
        )
        assert (await second_client.get("/api/v1/auth/me")).status_code == 200
