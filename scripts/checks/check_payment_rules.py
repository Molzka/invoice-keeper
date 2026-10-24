"""Check payment rules through the real HTTP API of a disposable local stack.

Usage: ADMIN_USERNAME=... ADMIN_PASSWORD=... python check_payment_rules.py http://localhost:8080
Uses only the standard library; never reads .env or contacts Telegram. Created
rules are stopped and users removed in finally. Payment history remains until
the disposable database is removed. Do not run against a working database.
"""

import argparse
import calendar
import json
import os
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

from check_backend import require


class Api:
    def __init__(self, origin, cache_errors):
        self.origin = origin
        self.transport = origin.replace("//0.0.0.0", "//127.0.0.1", 1)
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = None
        self.cache_errors = cache_errors

    def raw(self, method, path, body=None, params=None, headers=None):
        if params:
            path += "?" + urlencode(params)
        request_headers = {"Origin": self.origin, "Accept": "application/json"}
        payload = body
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            if not isinstance(body, bytes):
                payload = json.dumps(body).encode("utf-8")
        if self.csrf and method != "GET":
            request_headers["X-CSRF-Token"] = self.csrf
        request_headers.update(headers or {})
        url = self.transport + "/api/v1" + path
        try:
            response = self.opener.open(
                Request(url, payload, request_headers, method=method), timeout=45
            )
        except HTTPError as error:
            response = error
        with response:
            require(response.geturl() == url, f"{method} {path}: unexpected redirect")
            # Defer this assertion so successful creations can still be cleaned up.
            cache_control = {
                directive.strip().lower()
                for directive in response.headers.get("Cache-Control", "").split(",")
            }
            if "no-store" not in cache_control:
                self.cache_errors.add(f"{method} {path}")
            content = response.read()
            is_json = response.headers.get_content_type() == "application/json"
            require(
                not content or is_json or path.endswith("/receipt/file"), f"{path}: expected JSON"
            )
            return response.status, json.loads(content) if content and is_json else content or None

    def request(self, method, path, body=None, params=None, status=200, code=None, headers=None):
        actual, result = self.raw(method, path, body, params, headers)
        error_code = result.get("error", {}).get("code") if isinstance(result, dict) else None
        require(
            actual == status, f"{method} {path}: expected {status}, got {actual} ({error_code})"
        )
        if code:
            require(error_code == code, f"{method} {path}: expected error {code}, got {error_code}")
        return result

    def login(self, username, password):
        result = self.request("POST", "/auth/login", {"username": username, "password": password})
        self.csrf = result["csrf_token"]
        return result

    def periods(self, **filters):
        rows, total = [], None
        for offset in range(0, 100000, 100):
            page = self.request(
                "GET", "/payment-occurrences", params={**filters, "limit": 100, "offset": offset}
            )
            require(
                page["limit"] == 100 and page["offset"] == offset, "Incorrect pagination metadata"
            )
            if total is None:
                total = page["total"]
            require(
                page["total"] == total, "Periods changed during pagination; rerun on an idle stack"
            )
            rows.extend(page["items"])
            if len(rows) >= total:
                break
            require(bool(page["items"]), "API returned an incomplete page sequence")
        require(len(rows) == total, "Period listing is incomplete or exceeded the safety bound")
        require(
            len({item["id"] for item in rows}) == len(rows),
            "Period listing contains duplicate UUIDs",
        )
        return rows


def next_month(value):
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def history_state(rows):
    return {row["id"]: (row["due_date"], row["status"], row["paid_on"]) for row in rows}


def check_summary(client, today, timezone_name):
    start = date(2024, 1, 1)
    end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    filters = {"date_from": start.isoformat(), "date_to": end.isoformat()}
    summary = client.request("GET", "/payments/summary", params=filters)
    require(
        summary["as_of_date"] == today.isoformat() and summary["timezone"] == timezone_name,
        "Summary uses a different business date or timezone",
    )
    require(
        all(summary[key] == value for key, value in filters.items()),
        "Summary changed the date interval",
    )
    expected = {
        currency: dict.fromkeys(("planned", "paid", "unpaid", "overdue"), Decimal("0.00"))
        for currency in ("RUB", "USD", "EUR")
    }
    rows = client.periods(**filters)
    for row in rows:
        due = date.fromisoformat(row["due_date"])
        require(start <= due <= end, "Date filtering returned an out-of-range period")
        amount, totals = Decimal(row["amount"]), expected[row["currency"]]
        totals["planned"] += amount
        totals[row["status"]] += amount
        if row["status"] == "unpaid" and due < today:
            totals["overdue"] += amount
    require(
        set(summary["totals"]) == set(expected), "Summary currency keys differ from RUB/USD/EUR"
    )
    for currency, totals in expected.items():
        for field, amount in totals.items():
            actual = summary["totals"][currency][field]
            require(
                isinstance(actual, str) and re.fullmatch(r"[0-9]+\.[0-9]{2}", actual),
                f"Summary {currency}.{field} is not an exact two-decimal string",
            )
            require(
                Decimal(actual) == amount, f"Summary {currency}.{field} differs from listed periods"
            )
    require(
        client.request("GET", "/payments/summary", params=filters) == summary,
        "Summary changed during comparison; rerun on an idle stack",
    )
    print(
        f"PASS: Decimal summary matches all {len(rows)} paginated periods, including existing fixtures"
    )


def check(origin):
    admin_name, admin_password = os.environ["ADMIN_USERNAME"], os.environ["ADMIN_PASSWORD"]
    cache_errors = set()
    admin, user = Api(origin, cache_errors), Api(origin, cache_errors)
    suffix = secrets.token_hex(6)
    username, password = "payments_" + suffix, secrets.token_urlsafe(24)
    rule_ids, user_ids, receipt_paths, cleanup_errors = [], [], [], []

    def rule_body(title, amount, currency, due):
        return {
            "title": title + " " + suffix,
            "amount": amount,
            "currency": currency,
            "first_due_date": due.isoformat(),
            "periodicity": "monthly",
        }

    def create_rule(title, amount, currency, due):
        item = admin.request(
            "POST", "/recurring-payments", rule_body(title, amount, currency, due), status=201
        )
        rule_ids.append(item["id"])
        require(
            item["amount"] == amount and item["currency"] == currency,
            "Rule money changed during creation",
        )
        return item

    def forbidden(method, path, body=None):
        status, result = user.raw(method, path, body)
        if status == 201 and isinstance(result, dict) and "id" in result:
            (rule_ids if path == "/recurring-payments" else user_ids).append(result["id"])
        require(
            status == 403 and result.get("error", {}).get("code") == "FORBIDDEN",
            f"Ordinary user was not forbidden: {method} {path}, status {status}",
        )

    def update_payment(item, status, paid_on):
        result = user.request(
            "PATCH",
            "/payment-occurrences/" + item["id"],
            {
                "status": status,
                "paid_on": paid_on.isoformat() if paid_on else None,
            },
        )
        require(
            result["id"] == item["id"] and result["due_date"] == item["due_date"],
            "Payment update changed its identity or contractual due date",
        )
        return result

    try:
        for path in (
            "/recurring-payments",
            "/payment-occurrences",
            "/payments/summary",
            "/payments/budget?year=2024",
            "/users",
            "/audit-events",
        ):
            user.request("GET", path, status=401, code="AUTH_REQUIRED")
        auth = admin.login(admin_name, admin_password)
        require(auth["user"]["role"] == "admin", "Provided administrator is not an admin")
        zone = ZoneInfo(auth["timezone"])
        today = datetime.now(zone).date()
        require(today >= date(2024, 3, 31), "Historical scenario requires a date after March 2024")
        created_user = admin.request(
            "POST", "/users", {"username": username, "password": password}, status=201
        )
        user_ids.append(created_user["id"])
        user_auth = user.login(username, password)
        require(
            user_auth["user"]["role"] == "user" and user_auth["timezone"] == auth["timezone"],
            "Ordinary user role or shared timezone is wrong",
        )
        print(f"PASS: anonymous API denied; separate admin/user sessions use {auth['timezone']}")

        rub = create_rule("Rent integration", "45000.00", "RUB", date(2024, 1, 31))
        usd = create_rule("Server integration", "29.00", "USD", today - timedelta(days=1))
        eur = create_rule("Subscription integration", "12.00", "EUR", today)
        by_date = {row["due_date"]: row for row in user.periods(recurring_payment_id=rub["id"])}
        first_dates = ["2024-01-31", "2024-02-29", "2024-03-31"]
        require(
            all(value in by_date for value in first_dates),
            "31 Jan -> 29 Feb -> 31 Mar anchor was not preserved",
        )
        first = [by_date[value] for value in first_dates]
        require(len({row["id"] for row in first}) == 3, "Monthly periods reuse the same identity")
        require(
            all(row["status"] == "unpaid" and row["paid_on"] is None for row in first),
            "New periods do not have independent unpaid states",
        )
        yesterday = today - timedelta(days=1)
        usd_rows = user.periods(recurring_payment_id=usd["id"])
        usd_current = next(row for row in usd_rows if row["due_date"] == yesterday.isoformat())
        usd_next = next(
            row for row in usd_rows if row["due_date"] == next_month(yesterday).isoformat()
        )
        require(
            usd_current["is_overdue"] is True and usd_current["days_late"] == 1,
            "Yesterday's unpaid obligation is not exactly one day overdue",
        )
        require(
            usd_next["id"] != usd_current["id"] and usd_next["status"] == "unpaid",
            "Next period is missing or depends on payment of its predecessor",
        )
        eur_current = next(
            row
            for row in user.periods(recurring_payment_id=eur["id"])
            if row["due_date"] == today.isoformat()
        )
        require(
            eur_current["is_overdue"] is False and eur_current["days_late"] == 0,
            "A due-today period is incorrectly overdue",
        )
        print(
            "PASS: three currencies, leap February, original monthly anchor and separate next period"
        )

        due = date.fromisoformat(first[0]["due_date"])
        late = update_payment(first[0], "paid", due + timedelta(days=2))
        require(
            late["paid_late"] is True and late["days_late"] == 2 and late["is_overdue"] is False,
            "Late payment has incorrect flags or lateness",
        )
        corrected = update_payment(first[0], "paid", due)
        require(
            corrected["paid_late"] is False and corrected["days_late"] == 0,
            "Correcting actual payment date did not remove lateness",
        )
        cleared = update_payment(first[0], "unpaid", None)
        require(
            cleared["paid_on"] is None
            and cleared["status"] == "unpaid"
            and cleared["is_overdue"] is True,
            "Unpay did not clear the date and restore overdue state",
        )
        update_payment(first[0], "paid", due)
        paid_usd = update_payment(usd_current, "paid", today)
        require(
            paid_usd["paid_late"] is True and paid_usd["days_late"] == 1,
            "Yesterday's period paid today is not one day late",
        )
        update_payment(usd_current, "paid", yesterday)
        paid_eur = update_payment(eur_current, "paid", today)
        require(
            paid_eur["paid_late"] is False and paid_eur["days_late"] == 0,
            "Due-date payment is not timely",
        )
        for following in (first[1], usd_next):
            item = user.request("GET", "/payment-occurrences/" + following["id"])
            require(
                item["status"] == "unpaid" and item["paid_on"] is None,
                "Payment changed a different period",
            )
        print("PASS: late/on-time correction, unpay clears date, independent period states")

        forbidden("POST", "/recurring-payments", rule_body("Forbidden", "1.00", "RUB", today))
        forbidden("DELETE", "/recurring-payments/" + rub["id"])
        forbidden(
            "POST",
            "/users",
            {"username": username + "_blocked", "password": secrets.token_urlsafe(24)},
        )
        forbidden("PATCH", "/users/" + created_user["id"], {"username": username})
        forbidden("DELETE", "/users/" + created_user["id"])
        admin.request(
            "PATCH",
            "/users/" + auth["user"]["id"],
            {"username": admin_name},
            status=403,
            code="ADMIN_ACCOUNT_PROTECTED",
        )
        replacement = secrets.token_urlsafe(24)
        status, result = admin.raw(
            "POST",
            "/auth/change-password",
            {
                "current_password": admin_password,
                "new_password": replacement,
            },
        )
        if status == 200:
            admin.csrf = result["csrf_token"]
            restored = admin.request(
                "POST",
                "/auth/change-password",
                {
                    "current_password": replacement,
                    "new_password": admin_password,
                },
            )
            admin.csrf = restored["csrf_token"]
        require(
            status == 403 and result.get("error", {}).get("code") == "ADMIN_ACCOUNT_PROTECTED",
            f"Admin self-password change was not protected: {status}",
        )
        current = admin.request("GET", "/auth/me")
        require(
            current["user"]["id"] == auth["user"]["id"]
            and current["csrf_token"] == auth["csrf_token"],
            "Rejected administrator change altered the current session",
        )
        password_check = Api(origin, cache_errors)
        try:
            old_login = password_check.login(admin_name, admin_password)
            require(
                old_login["user"]["id"] == auth["user"]["id"],
                "Administrator's original password no longer works",
            )
        finally:
            if password_check.csrf:
                password_check.request("POST", "/auth/logout", status=204)
        print(
            "PASS: ordinary role cannot administer; administrator password and session are protected"
        )

        check_summary(user, today, auth["timezone"])
        for path in ("/recurring-payments", "/users", "/audit-events"):
            admin.request("GET", path)
        user.request("GET", "/payments/budget", params={"year": today.year})
        invalid = rule_body("Invalid\0title", "1.00", "RUB", today)
        status, result = admin.raw("POST", "/recurring-payments", invalid)
        if status == 201:
            rule_ids.append(result["id"])
        require(status == 422, f"NUL title: expected 422, got {status}")
        for field in ("actor", "query"):
            admin.request("GET", "/audit-events", params={field: "Invalid\0search"}, status=422)
        receipt_path = "/payment-occurrences/" + eur_current["id"] + "/receipt"
        receipt_paths.append(receipt_path)
        require(user.request("GET", receipt_path) is None, "New period already has a receipt")
        for label, body in (
            ("malformed", b"{"),
            ("5000-digit integer", b'{"url":' + b"1" * 5000 + b"}"),
            ("deep nesting", b"[" * 20000 + b"0" + b"]" * 20000),
        ):
            user.request("PUT", receipt_path, body, status=400, code="INVALID_JSON")
            require(
                user.request("GET", receipt_path) is None,
                f"Rejected {label} JSON changed the receipt",
            )
        pdf = b"%PDF-1.4\nIntegration receipt\n"
        user.request(
            "PUT",
            receipt_path,
            pdf,
            headers={"Content-Type": "application/pdf", "X-Filename": "check.pdf"},
        )
        require(
            user.request("GET", receipt_path + "/file") == pdf, "Receipt download changed its bytes"
        )
        user.request("DELETE", receipt_path, status=204)
        receipt_paths.remove(receipt_path)
        print(
            "PASS: NUL title/audit rejected; invalid JSON returns 400 without receipt side effects"
        )

        before = user.periods(recurring_payment_id=rub["id"])
        admin.request("DELETE", "/recurring-payments/" + rub["id"], status=204)
        after = user.periods(recurring_payment_id=rub["id"])
        require(
            history_state(after) == history_state(before), "Stopping a rule changed payment history"
        )
        require(
            all(row["recurring_payment_is_active"] is False for row in after),
            "Stopped rule still appears active",
        )
        require(
            datetime.now(zone).date() == today, "Business midnight crossed during the check; rerun"
        )
        print("PASS: stopping a rule preserves period IDs, dates, statuses and payment history")
    finally:
        for path in dict.fromkeys(receipt_paths):
            try:
                admin.request("DELETE", path, status=204)
            except Exception:
                cleanup_errors.append("delete fixture receipt")
        for rule_id in dict.fromkeys(rule_ids):
            try:
                admin.request("DELETE", "/recurring-payments/" + rule_id, status=204)
            except Exception:
                cleanup_errors.append("stop fixture rule")
        for user_id in dict.fromkeys(user_ids):
            try:
                status, _ = admin.raw("DELETE", "/users/" + user_id)
                require(status in {204, 404}, f"Cleanup user status {status}")
            except Exception:
                cleanup_errors.append("delete fixture user")
        if admin.csrf:
            try:
                admin.request("POST", "/auth/logout", status=204)
            except Exception:
                cleanup_errors.append("admin logout")
        if cleanup_errors:
            print("Cleanup failed: " + "; ".join(cleanup_errors), file=sys.stderr)
        if cache_errors:
            print("Missing no-store: " + "; ".join(sorted(cache_errors)), file=sys.stderr)
    require(not cleanup_errors, "Fixture cleanup failed")
    require(not cache_errors, "Private API responses must include Cache-Control: no-store")
    print(
        "PASS: financial responses are no-store; fixture rules stopped and users removed; history retained"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url", help="Origin of a disposable local test stack with no real notification worker"
    )
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (
        url.scheme not in {"http", "https"}
        or url.hostname not in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        parser.error("Provide a local HTTP(S) origin without credentials, path, query or fragment")
    try:
        check(args.url.rstrip("/"))
    except RuntimeError as error:
        print(f"Payment integration check failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "Payment integration check failed; inspect service logs. Credentials and response bodies omitted.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
