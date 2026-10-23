import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from sqlalchemy import select

from app.models import User

from .conftest import PASSWORD
from .test_auth import assert_error

pytestmark = pytest.mark.asyncio
NEW_PASSWORD = "another-strong-password-456"


async def test_users_require_authentication_and_admin_role(client, create_user, login):
    assert_error(await client.get("/api/v1/users"), 401, "AUTH_REQUIRED")
    await create_user("member", role="member")
    member_auth = await login(client, "member")
    assert_error(await client.get("/api/v1/users"), 403, "FORBIDDEN")
    assert_error(
        await client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": member_auth["csrf_token"]},
            json={
                "username": "newuser",
                "display_name": "New User",
                "password": PASSWORD,
            },
        ),
        403,
        "FORBIDDEN",
    )


async def test_admin_can_create_user_and_list_paginated_public_profiles(
    app, client, create_user, login
):
    await create_user()
    authentication = await login(client)
    response = await client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": authentication["csrf_token"]},
        json={"username": "newuser", "display_name": "New User", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["username"] == "newuser"
    assert created["display_name"] == "New User"
    assert created["role"] == "member"
    assert created["is_active"] is True
    assert "password" not in created
    assert "password_hash" not in created
    async with app.state.database.session_factory() as session:
        user = await session.scalar(select(User).where(User.username == "newuser"))
        assert user.password_hash != PASSWORD
        assert user.password_hash.startswith("$argon2id$")
        assert PasswordHash.recommended().verify(PASSWORD, user.password_hash)

    first = await client.get("/api/v1/users?limit=1&offset=0")
    second = await client.get("/api/v1/users?limit=1&offset=1")
    assert first.status_code == second.status_code == 200
    first_page, second_page = first.json(), second.json()
    assert first_page["total"] == second_page["total"] == 2
    assert first_page["limit"] == 1
    assert first_page["offset"] == 0
    assert second_page["offset"] == 1
    assert len(first_page["items"]) == len(second_page["items"]) == 1
    assert first_page["items"][0]["id"] != second_page["items"][0]["id"]
    assert "password" not in first.text
    assert "password" not in second.text


async def test_create_requires_csrf_and_duplicate_username_is_conflict(client, create_user, login):
    await create_user()
    authentication = await login(client)
    payload = {"username": "unique", "display_name": "Unique", "password": PASSWORD}
    assert_error(await client.post("/api/v1/users", json=payload), 403, "CSRF_INVALID")
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    assert (await client.post("/api/v1/users", json=payload, headers=headers)).status_code == 201
    assert_error(
        await client.post("/api/v1/users", json=payload, headers=headers),
        409,
        "USERNAME_TAKEN",
    )
    # A failed insert must not leave later requests in a failed transaction.
    assert (await client.get("/api/v1/users")).status_code == 200


async def test_last_active_admin_cannot_be_disabled_or_demoted(client, create_user, login):
    admin = await create_user()
    await create_user("disabled_admin", role="admin", is_active=False)
    authentication = await login(client)
    for payload in ({"role": "member"}, {"is_active": False}):
        assert_error(
            await client.patch(
                f"/api/v1/users/{admin.id}",
                json=payload,
                headers={"X-CSRF-Token": authentication["csrf_token"]},
            ),
            409,
            "LAST_ACTIVE_ADMIN",
        )
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["user"]["is_active"] is True


@pytest.mark.parametrize(
    "change", [{"is_active": False}, {"role": "admin"}, {"password": NEW_PASSWORD}]
)
async def test_sensitive_account_changes_revoke_all_target_sessions(
    app, client, create_user, login, change
):
    await create_user()
    member = await create_user("member", role="member")
    admin_auth = await login(client)
    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as first_member_client,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as second_member_client,
    ):
        await login(first_member_client, "member")
        await login(second_member_client, "member")
        response = await client.patch(
            f"/api/v1/users/{member.id}",
            json=change,
            headers={"X-CSRF-Token": admin_auth["csrf_token"]},
        )
        assert response.status_code == 200, response.text
        assert "password" not in response.json()
        assert "password_hash" not in response.json()
        assert_error(await first_member_client.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")
        assert_error(await second_member_client.get("/api/v1/auth/me"), 401, "AUTH_REQUIRED")
        assert (await client.get("/api/v1/auth/me")).status_code == 200

        if "password" in change:
            assert_error(
                await first_member_client.post(
                    "/api/v1/auth/login",
                    json={"username": "member", "password": PASSWORD},
                ),
                401,
                "INVALID_CREDENTIALS",
            )
            updated_auth = await login(first_member_client, "member", NEW_PASSWORD)
            assert updated_auth["user"]["id"] == str(member.id)


async def test_display_name_change_preserves_existing_session(client, create_user, login):
    admin = await create_user()
    authentication = await login(client)
    response = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"display_name": "Updated Name"},
        headers={"X-CSRF-Token": authentication["csrf_token"]},
    )
    assert response.status_code == 200
    current = await client.get("/api/v1/auth/me")
    assert current.status_code == 200
    assert current.json()["user"]["display_name"] == "Updated Name"


async def test_concurrent_admin_demotions_leave_an_active_admin(app, client, create_user, login):
    first_admin = await create_user()
    second_admin = await create_user("second_admin")
    first_auth = await login(client)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as second_client:
        second_auth = await login(second_client, "second_admin")
        responses = await asyncio.gather(
            client.patch(
                f"/api/v1/users/{first_admin.id}",
                json={"role": "member"},
                headers={"X-CSRF-Token": first_auth["csrf_token"]},
            ),
            second_client.patch(
                f"/api/v1/users/{second_admin.id}",
                json={"role": "member"},
                headers={"X-CSRF-Token": second_auth["csrf_token"]},
            ),
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with app.state.database.session_factory() as session:
        admins = (
            await session.scalars(
                select(User).where(User.role == "admin", User.is_active.is_(True))
            )
        ).all()
        assert len(admins) == 1


async def test_users_validate_roles_ids_and_pagination(client, create_user, login):
    admin = await create_user()
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    for url in ("/api/v1/users?limit=0", "/api/v1/users?offset=-1"):
        response = await client.get(url)
        assert response.status_code == 422
        assert "error" in response.json()
    response = await client.patch(
        f"/api/v1/users/{admin.id}", json={"role": "superuser"}, headers=headers
    )
    assert response.status_code == 422
    response = await client.patch(
        "/api/v1/users/not-a-uuid", json={"display_name": "Other Name"}, headers=headers
    )
    assert response.status_code == 422
    assert "error" in response.json()


async def test_usernames_are_normalized_before_unique_check(client, create_user, login):
    await create_user()
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    payload = {"username": " Mixed.Case ", "display_name": "Test", "password": PASSWORD}
    response = await client.post("/api/v1/users", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["username"] == "mixed.case"
    payload["username"] = "MIXED.CASE"
    assert_error(
        await client.post("/api/v1/users", json=payload, headers=headers), 409, "USERNAME_TAKEN"
    )
