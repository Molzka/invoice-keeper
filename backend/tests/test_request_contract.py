import pytest

from .conftest import PASSWORD
from .test_auth import assert_error

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "origin", [None, "null", "https://foreign.example", "", "http://testserver/path"]
)
async def test_login_rejects_missing_or_invalid_origin(client, origin):
    del client.headers["Origin"]
    headers = {"Origin": origin} if origin is not None else {"Referer": "http://testserver/docs"}
    response = await client.post(
        "/api/v1/auth/login", headers=headers, json={"username": "admin", "password": PASSWORD}
    )
    assert_error(response, 403, "ORIGIN_NOT_ALLOWED")


async def test_missing_origin_cannot_modify_or_delete_users(client, create_user, login):
    await create_user()
    user = await create_user("ordinary", role="user")
    authentication = await login(client)
    del client.headers["Origin"]
    headers = {"X-CSRF-Token": authentication["csrf_token"], "Referer": "http://testserver/users"}
    for method, path, payload in [
        ("POST", "/api/v1/users", {"username": "newuser", "password": PASSWORD}),
        ("PATCH", f"/api/v1/users/{user.id}", {"username": "renamed"}),
        ("DELETE", f"/api/v1/users/{user.id}", None),
        ("POST", "/api/v1/auth/logout", None),
    ]:
        assert_error(
            await client.request(method, path, json=payload, headers=headers),
            403,
            "ORIGIN_NOT_ALLOWED",
        )


async def test_invalid_json_is_400_without_echoing_input(client):
    secret = "secret-do-not-reflect"
    response = await client.post(
        "/api/v1/auth/login",
        content='{"username":"admin","password":"' + secret,
        headers={"Content-Type": "application/json"},
    )
    assert_error(response, 400, "INVALID_JSON")
    assert response.json()["error"]["details"] == []
    assert secret not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/auth/me?typo=1",
        "/users?limti=10",
        "/users?role=admin",
        "/health?unknown=1",
        "/ready?unknown=1",
    ],
)
async def test_unknown_query_parameters_are_rejected(client, create_user, login, path):
    await create_user()
    await login(client)
    response = await client.get("/api/v1" + path)
    assert_error(response, 422, "VALIDATION_ERROR")
    detail = response.json()["error"]["details"][0]
    assert set(detail) == {"field", "code", "message"}
    assert detail["field"].startswith("query.")
    assert detail["code"] == "UNKNOWN_QUERY_PARAMETER"


async def test_unknown_query_rejected_on_mutating_routes(client, create_user, login):
    await create_user()
    user = await create_user("ordinary", role="user")
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    for method, path, payload in [
        ("POST", "/auth/login", {"username": "admin", "password": PASSWORD}),
        ("POST", "/auth/logout", None),
        ("POST", "/users", {"username": "newuser", "password": PASSWORD}),
        ("PATCH", f"/users/{user.id}", {"password": "newpass8"}),
        ("DELETE", f"/users/{user.id}", None),
    ]:
        assert_error(
            await client.request(
                method, "/api/v1" + path + "?typo=1", json=payload, headers=headers
            ),
            422,
            "VALIDATION_ERROR",
        )
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_validation_errors_identify_body_query_and_path_fields(client, create_user, login):
    await create_user()
    authentication = await login(client)
    headers = {"X-CSRF-Token": authentication["csrf_token"]}
    for method, path, payload, expected in [
        ("POST", "/users", {"username": "short", "password": "secret"}, "password"),
        ("GET", "/users?limit=0", None, "query.limit"),
        ("PATCH", "/users/not-a-uuid", {"username": "renamed"}, "path.user_id"),
    ]:
        response = await client.request(method, "/api/v1" + path, json=payload, headers=headers)
        assert_error(response, 422, "VALIDATION_ERROR")
        detail = response.json()["error"]["details"][0]
        assert set(detail) == {"field", "code", "message"}
        assert detail["field"] == expected
        assert isinstance(detail["message"], str) and detail["message"]
        assert "secret" not in response.text


async def test_cors_allows_frontend_delete_with_csrf(client):
    response = await client.options(
        "/api/v1/users/unused",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://testserver"
    assert "DELETE" in response.headers["access-control-allow-methods"]
