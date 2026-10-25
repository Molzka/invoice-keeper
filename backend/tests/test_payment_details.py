from datetime import date

import pytest

from tests.test_payment_amounts import periods, setup_payment

pytestmark = pytest.mark.asyncio


async def test_edit_name_and_convert_once_without_losing_payment_or_receipt(
    client, create_user, login, monkeypatch
):
    today = date(2027, 3, 15)
    monkeypatch.setattr("app.api.payment_lifecycle.today_in_timezone", lambda _: today)
    monkeypatch.setattr("app.api.payments.today_in_timezone", lambda _: today)
    await create_user()
    headers = {"X-CSRF-Token": (await login(client))["csrf_token"]}
    created = await client.post(
        "/api/v1/one-time-payments",
        json={"title": "Server", "amount": "10.00", "currency": "USD", "due_date": "2027-01-31"},
        headers=headers,
    )
    assert created.status_code == 201
    item = created.json()
    path = f"/api/v1/payment-occurrences/{item['id']}"
    assert (
        await client.patch(path, json={"status": "paid", "paid_on": "2027-01-30"}, headers=headers)
    ).status_code == 200
    assert (
        await client.put(
            path + "/receipt", json={"url": "https://example.com/receipt"}, headers=headers
        )
    ).status_code == 200
    payload = {"title": "Hosting", "periodicity": "monthly"}
    for _ in range(2):
        response = await client.patch(path + "/details", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == item["id"]
    rows = await periods(client, item["recurring_payment_id"])
    assert list(rows) == ["2027-01-31", "2027-02-28", "2027-03-31"]
    assert all(
        row["title"] == "Hosting" and row["periodicity"] == "monthly" for row in rows.values()
    )
    assert rows["2027-01-31"]["paid_on"] == "2027-01-30"
    assert (await client.get(path + "/receipt")).json()["url"] == "https://example.com/receipt"
    denied = await client.patch(
        path + "/details",
        json={"title": "Must not save", "amount": "20.00", "currency": "EUR"},
        headers=headers,
    )
    assert denied.status_code == 409
    assert (await client.get(path)).json()["title"] == "Hosting"


async def test_details_validate_permissions_and_update_amount_atomically(
    client, create_user, login
):
    rule, headers = await setup_payment(client, create_user, login)
    item = next(iter((await periods(client, rule["id"])).values()))
    path = f"/api/v1/payment-occurrences/{item['id']}/details"
    for payload in [
        {"title": ""},
        {"title": "x", "amount": "1.00"},
        {"title": "x", "currency": "EUR"},
        {"title": "x", "periodicity": "once"},
        {"title": "x", "amount": None, "currency": None},
    ]:
        assert (await client.patch(path, json=payload, headers=headers)).status_code == 422
    assert (await client.patch(path, json={"title": "x"})).status_code == 403
    updated = await client.patch(
        path, json={"title": "Renamed", "amount": "12.50", "currency": "EUR"}, headers=headers
    )
    assert updated.status_code == 200, updated.text
    rows = await periods(client, rule["id"])
    assert all(row["title"] == "Renamed" for row in rows.values())
    assert rows[item["due_date"]]["amount"] == "12.50"
    assert all(row["amount"] == "10.00" for row in rows.values() if row["id"] != item["id"])
    regular = await client.patch(
        f"/api/v1/recurring-payments/{rule['id']}",
        json={"title": "New name", "amount": "10.00", "currency": "RUB"},
        headers=headers,
    )
    assert regular.status_code == 200, regular.text
    assert regular.json()["payment"]["title"] == "New name"
    await create_user("member", role="user")
    member_headers = {"X-CSRF-Token": (await login(client, "member"))["csrf_token"]}
    assert (
        await client.patch(path, json={"title": "Forbidden"}, headers=member_headers)
    ).status_code == 403
