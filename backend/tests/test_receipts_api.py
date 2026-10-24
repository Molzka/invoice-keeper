import asyncio
from datetime import date
from decimal import Decimal
from urllib.parse import quote
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import AuditEvent, PaymentOccurrence, RecurringPayment
from app.models.payment_receipt import MAX_RECEIPT_BYTES, PaymentReceipt
from app.services.payments import today_in_timezone

from .test_auth import assert_error

pytestmark = pytest.mark.asyncio
PDF = b"%PDF-1.7\nreceipt test document\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\nreceipt test image"
JPEG = b"\xff\xd8\xff\xe0receipt test image\xff\xd9"


async def seed_occurrences(app, *, active=True):
    today = today_in_timezone(app.state.settings.app_timezone)
    async with app.state.database.session_factory() as db:
        payment = RecurringPayment(
            title="Office receipt",
            amount=Decimal("10.00"),
            currency="RUB",
            first_due_date=today,
            periodicity="monthly",
            anchor_day=today.day,
            is_active=active,
        )
        db.add(payment)
        await db.flush()
        periods = [
            PaymentOccurrence(
                recurring_payment_id=payment.id,
                due_date=today,
                amount=payment.amount,
                currency=payment.currency,
            ),
            PaymentOccurrence(
                recurring_payment_id=payment.id,
                amount=payment.amount,
                currency=payment.currency,
                due_date=date(today.year + 1, today.month, min(today.day, 28)),
            ),
        ]
        db.add_all(periods)
        await db.commit()
        return [str(period.id) for period in periods], str(payment.id)


def path(occurrence_id):
    return f"/api/v1/payment-occurrences/{occurrence_id}/receipt"


async def setup_authenticated(app, client, create_user, login, *, role="admin", active=True):
    user = await create_user(role=role)
    auth = await login(client)
    ids, payment_id = await seed_occurrences(app, active=active)
    return ids, payment_id, {"X-CSRF-Token": auth["csrf_token"]}, user


async def audit_events(app):
    async with app.state.database.session_factory() as db:
        return list((await db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at))).all())


async def test_receipts_require_auth_before_reading_upload(app, client):
    ids, _ = await seed_occurrences(app)
    for method, suffix in [("GET", ""), ("GET", "/file"), ("DELETE", "")]:
        response = await client.request(method, path(ids[0]) + suffix)
        assert_error(response, 401, "AUTH_REQUIRED")

    async def untouched_body():
        raise AssertionError("An unauthenticated upload body must not be consumed")
        yield b""

    response = await client.put(
        path(ids[0]), content=untouched_body(), headers={"Content-Type": "application/pdf"}
    )
    assert_error(response, 401, "AUTH_REQUIRED")


@pytest.mark.parametrize("role", ["admin", "user"])
async def test_both_roles_can_manage_link_without_exposing_it_in_audit(
    app, client, create_user, login, role
):
    ids, payment_id, headers, user = await setup_authenticated(
        app, client, create_user, login, role=role
    )
    assert (await client.get(path(ids[0]))).json() is None
    url = "https://example.com/private-receipt?token=secret-proof-token"
    response = await client.put(path(ids[0]), json={"url": url}, headers=headers)
    assert response.status_code == 200, response.text
    metadata = response.json()
    assert set(metadata) == {
        "id",
        "kind",
        "url",
        "filename",
        "content_type",
        "size_bytes",
        "uploaded_at",
    }
    assert metadata["kind"] == "link" and metadata["url"] == url
    assert metadata["filename"] is metadata["content_type"] is metadata["size_bytes"] is None
    assert metadata["uploaded_at"].endswith("Z")
    assert (await client.get(path(ids[0]))).json() == metadata
    assert (await client.get(path(ids[1]))).json() is None
    assert_error(await client.get(path(ids[0]) + "/file"), 404, "RECEIPT_FILE_NOT_FOUND")

    # The same PUT is idempotent, including its audit side effect and timestamp.
    repeated = await client.put(path(ids[0]), json={"url": url}, headers=headers)
    assert repeated.json() == metadata
    events = await audit_events(app)
    assert len(events) == 1
    assert events[0].action == "payment.receipt_updated"
    assert events[0].actor_id == user.id
    assert str(events[0].entity_id) == payment_id
    assert "secret-proof-token" not in str(events[0].changes)
    assert "example.com" not in str(events[0].changes)

    assert (await client.delete(path(ids[0]), headers=headers)).status_code == 204
    assert (await client.delete(path(ids[0]), headers=headers)).status_code == 204
    assert (await client.get(path(ids[0]))).json() is None
    assert [event.action for event in await audit_events(app)] == [
        "payment.receipt_updated",
        "payment.receipt_deleted",
    ]


@pytest.mark.parametrize(
    ("content_type", "body", "suffix"),
    [("application/pdf", PDF, ".pdf"), ("image/png", PNG, ".png"), ("image/jpeg", JPEG, ".jpg")],
)
async def test_upload_download_and_safely_replace_file(
    app, client, create_user, login, content_type, body, suffix
):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    filename = quote("../../Чек\r\n<img>.html", safe="")
    file_headers = {**headers, "Content-Type": content_type, "X-Filename": filename}
    response = await client.put(path(ids[0]), content=body, headers=file_headers)
    assert response.status_code == 200, response.text
    metadata = response.json()
    assert metadata["kind"] == "file"
    assert metadata["url"] is None
    assert metadata["content_type"] == content_type
    assert metadata["size_bytes"] == len(body)
    assert metadata["filename"].endswith(suffix)
    assert all(char not in metadata["filename"] for char in "\r\n/\\")

    # Original filenames never reach download headers, even when percent-encoded.
    downloaded = await client.get(path(ids[0]) + "/file")
    assert downloaded.content == body
    assert downloaded.headers["content-type"] == content_type
    assert downloaded.headers["content-disposition"] == f'attachment; filename="receipt{suffix}"'
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-security-policy"] == "sandbox"
    assert downloaded.headers["cache-control"] == "no-store"
    assert "data" not in metadata
    assert (await client.put(path(ids[0]), content=body, headers=file_headers)).json() == metadata
    assert len(await audit_events(app)) == 1

    replaced = await client.put(
        path(ids[0]), json={"url": "https://example.com/proof"}, headers=headers
    )
    assert replaced.status_code == 200
    assert replaced.json()["id"] == metadata["id"]
    assert replaced.json()["filename"] is None
    assert_error(await client.get(path(ids[0]) + "/file"), 404, "RECEIPT_FILE_NOT_FOUND")
    assert len(await audit_events(app)) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/receipt",
        "javascript:alert(1)",
        "data:text/html,x",
        "https://user:password@example.com/receipt",
        "https:///receipt",
        "https:example.com/receipt",
        "https://",
        " https://example.com",
        "https://example.com/with space",
        "https://example.com\n/x",
        "https://example.com:bad/x",
        "https://example.com:0/x",
        "https://example.com\\@else.test/x",
        "https://example.com/" + "x" * 2048,
    ],
)
async def test_invalid_links_are_rejected_with_field_errors(app, client, create_user, login, url):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    response = await client.put(path(ids[0]), json={"url": url}, headers=headers)
    assert_error(response, 422, "VALIDATION_ERROR")
    detail = response.json()["error"]["details"][0]
    assert set(detail) == {"field", "code", "message"}
    assert detail["field"] == "url"
    assert (await client.get(path(ids[0]))).json() is None
    assert await audit_events(app) == []


@pytest.mark.parametrize("payload", [{}, {"url": 3}, {"url": "https://example.com", "extra": True}])
async def test_link_json_contract_forbids_unknown_fields(app, client, create_user, login, payload):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    assert_error(
        await client.put(path(ids[0]), json=payload, headers=headers), 422, "VALIDATION_ERROR"
    )


async def test_receipt_invalid_json_unknown_query_and_unsupported_types(
    app, client, create_user, login
):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    assert_error(
        await client.put(
            path(ids[0]),
            content=b'{"url":',
            headers={**headers, "Content-Type": "application/json"},
        ),
        400,
        "INVALID_JSON",
    )
    assert_error(await client.get(path(ids[0]) + "?typo=1"), 422, "VALIDATION_ERROR")
    for mime in ["image/svg+xml", "text/html", "application/octet-stream", "multipart/form-data"]:
        response = await client.put(
            path(ids[0]), content=PDF, headers={**headers, "Content-Type": mime}
        )
        assert_error(response, 415, "UNSUPPORTED_RECEIPT_TYPE")
    for body in [b"", b"<html>fake PDF</html>", PNG]:
        response = await client.put(
            path(ids[0]), content=body, headers={**headers, "Content-Type": "application/pdf"}
        )
        assert_error(response, 422, "VALIDATION_ERROR")
        assert response.json()["error"]["details"][0]["field"] == "file"


async def test_upload_limit_is_enforced_for_stream_without_content_length(
    app, client, create_user, login
):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    exact = b"%PDF-" + b"x" * (MAX_RECEIPT_BYTES - 5)
    uploaded = await client.put(
        path(ids[0]), content=exact, headers={**headers, "Content-Type": "application/pdf"}
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["size_bytes"] == MAX_RECEIPT_BYTES

    async def oversized_stream():
        yield exact[:200]
        yield exact[200:]
        yield b"x"

    response = await client.put(
        path(ids[0]),
        content=oversized_stream(),
        headers={**headers, "Content-Type": "application/pdf"},
    )
    assert "content-length" not in response.request.headers
    assert_error(response, 413, "RECEIPT_TOO_LARGE")
    assert (await client.get(path(ids[0]))).json() == uploaded.json()
    assert len(await audit_events(app)) == 1


async def test_receipt_mutations_require_origin_and_csrf(app, client, create_user, login):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    assert_error(
        await client.put(path(ids[0]), json={"url": "https://example.com"}), 403, "CSRF_FAILED"
    )
    assert_error(await client.delete(path(ids[0])), 403, "CSRF_FAILED")
    assert_error(
        await client.put(
            path(ids[0]),
            json={"url": "https://example.com"},
            headers={**headers, "Origin": "https://bad.test"},
        ),
        403,
        "ORIGIN_NOT_ALLOWED",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", cookies=client.cookies
    ) as no_origin:
        assert_error(
            await no_origin.put(path(ids[0]), json={"url": "https://example.com"}, headers=headers),
            403,
            "ORIGIN_NOT_ALLOWED",
        )


async def test_missing_occurrences_are_distinct_from_missing_receipts(
    app, client, create_user, login
):
    _, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    missing = path(uuid4())
    for method, suffix in [("GET", ""), ("GET", "/file"), ("DELETE", "")]:
        assert_error(
            await client.request(method, missing + suffix, headers=headers),
            404,
            "PAYMENT_OCCURRENCE_NOT_FOUND",
        )
    assert_error(
        await client.put(missing, json={"url": "https://example.com"}, headers=headers),
        404,
        "PAYMENT_OCCURRENCE_NOT_FOUND",
    )


async def test_receipts_are_independent_of_paid_state_and_stopped_rule(
    app, client, create_user, login
):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login, active=False)
    link = await client.put(
        path(ids[0]), json={"url": "https://example.com/proof"}, headers=headers
    )
    assert link.status_code == 200
    occurrence_path = f"/api/v1/payment-occurrences/{ids[0]}"
    today = today_in_timezone(app.state.settings.app_timezone).isoformat()
    paid = await client.patch(
        occurrence_path, json={"status": "paid", "paid_on": today}, headers=headers
    )
    assert paid.status_code == 200
    unpaid = await client.patch(
        occurrence_path, json={"status": "unpaid", "paid_on": None}, headers=headers
    )
    assert unpaid.status_code == 200
    assert (await client.get(path(ids[0]))).json() == link.json()
    assert (await client.get(path(ids[1]))).json() is None
    from app.delivery.schema import deliveries

    async with app.state.database.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(deliveries)) == 0


async def test_receipt_and_audit_roll_back_together(app, client, create_user, login, monkeypatch):
    import app.services.receipts as receipt_service

    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    saved = await client.put(
        path(ids[0]), content=PDF, headers={**headers, "Content-Type": "application/pdf"}
    )
    assert saved.status_code == 200
    original_events = await audit_events(app)
    original = receipt_service.record_audit_event

    def failed_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(receipt_service, "record_audit_event", failed_audit)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
        cookies=client.cookies,
        headers={"Origin": "http://testserver"},
    ) as api_client:
        response = await api_client.put(
            path(ids[0]), json={"url": "https://example.com/proof"}, headers=headers
        )
    assert_error(response, 500, "INTERNAL_ERROR")
    assert (await client.get(path(ids[0]))).json() == saved.json()
    assert (await client.get(path(ids[0]) + "/file")).content == PDF
    assert [event.id for event in await audit_events(app)] == [
        event.id for event in original_events
    ]


async def test_concurrent_receipt_updates_keep_one_complete_record(app, client, create_user, login):
    ids, _, headers, _ = await setup_authenticated(app, client, create_user, login)
    results = await asyncio.gather(
        client.put(path(ids[0]), json={"url": "https://example.com/proof"}, headers=headers),
        client.put(
            path(ids[0]), content=PDF, headers={**headers, "Content-Type": "application/pdf"}
        ),
    )
    assert [response.status_code for response in results] == [200, 200]
    metadata = (await client.get(path(ids[0]))).json()
    if metadata["kind"] == "file":
        assert metadata["url"] is None
        assert (await client.get(path(ids[0]) + "/file")).content == PDF
    else:
        assert metadata["url"] == "https://example.com/proof"
        assert metadata["size_bytes"] is None
        assert_error(await client.get(path(ids[0]) + "/file"), 404, "RECEIPT_FILE_NOT_FOUND")
    async with app.state.database.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(PaymentReceipt)) == 1
    assert len(await audit_events(app)) == 2


async def test_receipt_database_constraints_and_cascade(app):
    ids, _ = await seed_occurrences(app)
    async with app.state.database.session_factory() as db:
        receipt = PaymentReceipt(
            occurrence_id=ids[0],
            kind="file",
            filename="receipt.pdf",
            content_type="application/pdf",
            size_bytes=len(PDF),
            data=PDF,
        )
        db.add(receipt)
        await db.commit()
        for change in [
            {"kind": "invalid"},
            {"size_bytes": None},
            {"content_type": None},
            {"size_bytes": 1},
            {"url": "https://example.com"},
            {"data": None},
        ]:
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    for key, value in change.items():
                        setattr(receipt, key, value)
                    await db.flush()
            await db.refresh(receipt)
        duplicate = PaymentReceipt(occurrence_id=ids[0], kind="link", url="https://example.com")
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(duplicate)
                await db.flush()
        period = await db.get(PaymentOccurrence, ids[0])
        await db.delete(period)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(PaymentReceipt)) == 0
