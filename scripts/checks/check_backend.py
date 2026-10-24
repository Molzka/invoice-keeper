"""Check real authentication through Nginx on a disposable Compose database."""

import argparse
import json
import os
import secrets
import sys
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check(origin):
    username = os.environ["ADMIN_USERNAME"]
    password = os.environ["ADMIN_PASSWORD"]
    cookies = CookieJar()
    client = build_opener(HTTPCookieProcessor(cookies))

    def request(path, status=200, method="GET", body=None, csrf=None, source=origin):
        headers = {"Accept": "application/json"}
        if source is not None:
            headers["Origin"] = source
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        if body is not None:
            headers["Content-Type"] = "application/json"
        data = None if body is None else json.dumps(body).encode()
        try:
            response = client.open(Request(origin + path, data, headers, method=method), timeout=10)
        except HTTPError as error:
            response = error
        with response:
            require(
                response.status == status,
                f"{method} {path}: HTTP {response.status}, expected {status}",
            )
            require(response.geturl() == origin + path, f"{path}: unexpected redirect")
            content = response.read()
            require(
                password.encode() not in content,
                f"{path}: response disclosed administrator password",
            )
            if status != 204:
                require(
                    response.headers.get_content_type() == "application/json",
                    f"{path}: expected JSON",
                )
            payload = json.loads(content) if content else None
            return payload, response.headers

    # Nginx may still hold the old address immediately after container replacement.
    deadline = time.monotonic() + 30
    while True:
        try:
            ready, _ = request("/api/v1/ready")
            require(ready == {"status": "ok"}, "Unexpected readiness response")
            break
        except (RuntimeError, URLError, OSError):
            if time.monotonic() >= deadline:
                raise RuntimeError("API did not become ready through Nginx") from None
            time.sleep(1)

    health, _ = request("/api/v1/health")
    require(health == {"status": "ok"}, "Unexpected health response")
    schema, _ = request("/api/v1/openapi.json")
    require("/api/v1/auth/login" in schema["paths"], "API prefix was lost by proxy")
    request("/api/v1/no-such-route", 404)
    request("/api/v1/auth/me", 401)
    login_data = {"username": username, "password": password}
    for source in (None, "https://untrusted.invalid"):
        denied, _ = request("/api/v1/auth/login", 403, "POST", login_data, source=source)
        require(denied["error"]["code"] == "ORIGIN_NOT_ALLOWED", "Origin check failed")

    logged_in, headers = request("/api/v1/auth/login", method="POST", body=login_data)
    require(logged_in["user"]["role"] == "admin", "Bootstrap account is not an administrator")
    cookie = headers.get("Set-Cookie", "").lower()
    require("httponly" in cookie and "samesite=lax" in cookie, "Missing session cookie protections")
    require("no-store" in headers.get("Cache-Control", ""), "Authentication response is cacheable")
    require(bool(list(cookies)), "Proxy did not deliver a usable session cookie")
    me, _ = request("/api/v1/auth/me")
    require(me["user"]["id"] == logged_in["user"]["id"], "Session was not restored")
    csrf = me["csrf_token"]
    denied, _ = request("/api/v1/auth/logout", 403, "POST")
    require(denied["error"]["code"] == "CSRF_FAILED", "Missing CSRF token was accepted")

    member_name = "compose_" + secrets.token_hex(6)
    member_password = secrets.token_urlsafe(24)
    member, _ = request(
        "/api/v1/users", 201, "POST", {"username": member_name, "password": member_password}, csrf
    )
    require(member["role"] == "user", "Created account has an incorrect role")
    users, _ = request("/api/v1/users?limit=100&offset=0")
    require(any(user["id"] == member["id"] for user in users["items"]), "Created user is absent")
    require(
        all(user["role"] == "user" for user in users["items"]),
        "Administrator leaked into user list",
    )
    member_path = "/api/v1/users/" + member["id"]
    changed, _ = request(member_path, 200, "PATCH", {"username": member_name + "_new"}, csrf)
    require(changed["username"] == member_name + "_new", "User update did not persist")
    protected, _ = request("/api/v1/users/" + me["user"]["id"], 403, "DELETE", csrf=csrf)
    require(
        protected["error"]["code"] == "ADMIN_ACCOUNT_PROTECTED", "Administrator is not protected"
    )
    request(member_path, 204, "DELETE", csrf=csrf)
    users, _ = request("/api/v1/users?limit=100&offset=0")
    require(not any(user["id"] == member["id"] for user in users["items"]), "Deleted user remains")
    request("/api/v1/auth/logout", 204, "POST", csrf=csrf)
    request("/api/v1/auth/me", 401)
    print(
        "Nginx/API checks passed: readiness, prefix, Origin, cookie session, CSRF, users and logout"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Frontend origin of an isolated test Compose project")
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (
        url.scheme not in {"http", "https"}
        or not url.netloc
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        parser.error("Provide an HTTP(S) origin without a path, query or fragment")
    try:
        check(args.url.rstrip("/"))
    except RuntimeError as error:
        print(f"Backend integration check failed: {error}", file=sys.stderr)
        return 1
    except (URLError, OSError, ValueError, KeyError):
        # Do not print response bodies, passwords, cookies or CSRF tokens on failure.
        print(
            "Backend integration check failed; inspect the failed CI step and service logs.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
