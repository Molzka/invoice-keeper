import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from sqlalchemy import func, select

from app.models import User, UserSession

from .conftest import PASSWORD
from .test_auth import assert_error

pytestmark = pytest.mark.asyncio


async def test_users_require_authentication_and_admin_role(client, create_user, login):
    assert_error(await client.get("/api/v1/users"), 401, "AUTH_REQUIRED")
    user = await create_user("ordinary", role="user")
    authentication = await login(client, "ordinary")
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    assert_error(await client.get("/api/v1/users"), 403, "FORBIDDEN")
    for method, path, payload in [
        ("POST", "/api/v1/users", {"username": "newuser", "password": PASSWORD}),
        ("PATCH", f"/api/v1/users/{user.id}", {"username": "renamed"}),
        ("DELETE", f"/api/v1/users/{user.id}", None),
    ]:
        assert_error(
            await client.request(method, path, json=payload, headers=headers), 403, "FORBIDDEN"
        )


async def test_create_with_eight_character_password_and_list_only_ordinary_users(
    app, client, create_user, login
):
    await create_user()
    await create_user("second_admin")
    authentication = await login(client)
    response = await client.post(
        "/api/v1/users",
        json={"username": "newuser", "password": "12345678"},
        headers={"X-CSRF-Token": authentication["csrf_token"]},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert set(created) == {"id", "username", "role", "created_at"}
    assert created["role"] == "user"
    assert created["created_at"].endswith("Z")
    async with app.state.database.session_factory() as session:
        user = await session.scalar(select(User).where(User.username == "newuser"))
        assert PasswordHash.recommended().verify("12345678", user.password_hash)
    await create_user("another", role="user")
    first = (await client.get("/api/v1/users?limit=1&offset=0")).json()
    second = (await client.get("/api/v1/users?limit=1&offset=1")).json()
    assert first == {"items": [first["items"][0]], "total": 2, "limit": 1, "offset": 0}
    assert second["total"] == 2 and second["offset"] == 1
    assert first["items"][0]["username"] == "another"
    assert second["items"][0]["username"] == "newuser"


async def test_admin_only_list_is_empty(client, create_user, login):
    await create_user()
    await login(client)
    assert (await client.get("/api/v1/users")).json() == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }


@pytest.mark.parametrize(
    "field,value",
    [("role", "admin"), ("role", "user"), ("display_name", "Name"), ("is_active", False)],
)
async def test_create_and_patch_reject_fields_outside_contract(
    client, create_user, login, field, value
):
    await create_user()
    user = await create_user("ordinary", role="user")
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    for method, path, payload in [
        ("POST", "/api/v1/users", {"username": "newuser", "password": PASSWORD, field: value}),
        ("PATCH", f"/api/v1/users/{user.id}", {"username": "renamed", field: value}),
    ]:
        response = await client.request(method, path, json=payload, headers=headers)
        assert_error(response, 422, "VALIDATION_ERROR")
        detail = next(
            item for item in response.json()["error"]["details"] if item["field"] == field
        )
        assert detail["code"] == "UNKNOWN_FIELD"
        assert set(detail) == {"field", "code", "message"}


async def test_create_and_rename_conflicts_are_field_errors_and_rollback_sessions(
    app, client, create_user, login
):
    await create_user()
    user = await create_user("ordinary", role="user")
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as ordinary:
        await login(ordinary, "ordinary")
        for method, path, payload in [
            ("POST", "/api/v1/users", {"username": " ADMIN ", "password": PASSWORD}),
            ("PATCH", f"/api/v1/users/{user.id}", {"username": "admin", "password": "newpass8"}),
        ]:
            response = await client.request(method, path, json=payload, headers=headers)
            assert_error(response, 409, "USERNAME_TAKEN")
            assert response.json()["error"]["details"][0]["field"] == "username"
        assert (await ordinary.get("/api/v1/auth/me")).status_code == 200
        await login(ordinary, "ordinary")


@pytest.mark.parametrize("payload", [{"username": "renamed_admin"}, {"password": "newpass8"}])
async def test_all_admin_accounts_are_protected_from_patch_and_delete(
    client, create_user, login, payload
):
    first = await create_user()
    second = await create_user("second_admin")
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    for admin in (first, second):
        assert_error(
            await client.patch(f"/api/v1/users/{admin.id}", json=payload, headers=headers),
            403,
            "ADMIN_ACCOUNT_PROTECTED",
        )
        assert_error(
            await client.delete(f"/api/v1/users/{admin.id}", headers=headers),
            403,
            "ADMIN_ACCOUNT_PROTECTED",
        )
    assert (await client.get("/api/v1/auth/me")).json()["user"]["username"] == "admin"


@pytest.mark.parametrize(
    "change",
    [
        {"username": "renamed"},
        {"password": "newpass8"},
        {"username": "renamed", "password": "newpass8"},
    ],
)
async def test_username_and_password_changes_revoke_all_sessions(
    app, client, create_user, login, change
):
    await create_user()
    user = await create_user("ordinary", role="user")
    authentication = await login(client)
    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as first,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as second,
    ):
        await login(first, "ordinary")
        await login(second, "ordinary")
        response = await client.patch(
            f"/api/v1/users/{user.id}",
            json=change,
            headers={"X-CSRF-Token": authentication["csrf_token"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["username"] == change.get("username", "ordinary")
        for ordinary in (first, second):
            assert_error(await ordinary.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")
        assert_error(
            await first.post(
                "/api/v1/auth/login", json={"username": "ordinary", "password": PASSWORD}
            ),
            401,
            "INVALID_CREDENTIALS",
        )
        await login(first, change.get("username", "ordinary"), change.get("password", PASSWORD))
        assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_delete_user_revokes_all_sessions_and_removes_only_target(
    app, client, create_user, login
):
    admin = await create_user()
    user = await create_user("ordinary", role="user")
    await create_user("untouched", role="user")
    authentication = await login(client)
    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as ordinary,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as other_session,
    ):
        await login(ordinary, "ordinary")
        await login(other_session, "ordinary")
        assert_error(await client.delete(f"/api/v1/users/{user.id}"), 403, "CSRF_FAILED")
        response = await client.delete(
            f"/api/v1/users/{user.id}", headers={"X-CSRF-Token": authentication["csrf_token"]}
        )
        assert response.status_code == 204 and response.content == b""
        assert_error(await ordinary.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")
        assert_error(await other_session.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")
        assert_error(
            await ordinary.post(
                "/api/v1/auth/login", json={"username": "ordinary", "password": PASSWORD}
            ),
            401,
            "INVALID_CREDENTIALS",
        )
    async with app.state.database.session_factory() as session:
        assert await session.get(User, user.id) is None
        assert await session.get(User, admin.id) is not None
        assert (
            await session.scalar(
                select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
            )
            == 0
        )
    assert (await client.get("/api/v1/users")).json()["items"][0]["username"] == "untouched"


@pytest.mark.parametrize(
    "payload", [{}, {"username": None}, {"password": None}, {"password": "1234567"}]
)
async def test_invalid_patch_is_rejected(client, create_user, login, payload):
    await create_user()
    user = await create_user("ordinary", role="user")
    authentication = await login(client)
    assert_error(
        await client.patch(
            f"/api/v1/users/{user.id}",
            json=payload,
            headers={"X-CSRF-Token": authentication["csrf_token"]},
        ),
        422,
        "VALIDATION_ERROR",
    )


async def test_unknown_and_invalid_user_ids(client, create_user, login):
    await create_user()
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    for user_id, status, code in [
        (str(uuid4()), 404, "USER_NOT_FOUND"),
        ("invalid", 422, "VALIDATION_ERROR"),
    ]:
        assert_error(
            await client.patch(
                f"/api/v1/users/{user_id}", json={"username": "renamed"}, headers=headers
            ),
            status,
            code,
        )
        assert_error(await client.delete(f"/api/v1/users/{user_id}", headers=headers), status, code)


async def test_concurrent_renames_keep_unique_usernames(app, client, create_user, login):
    await create_user()
    first = await create_user("first", role="user")
    second = await create_user("second", role="user")
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    responses = await asyncio.gather(
        *[
            client.patch(f"/api/v1/users/{user.id}", json={"username": "shared"}, headers=headers)
            for user in (first, second)
        ]
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with app.state.database.session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(User).where(User.role == "user"))
            == 2
        )
