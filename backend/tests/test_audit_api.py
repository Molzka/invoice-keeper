from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.models import AuditEvent
from app.services.audit import record_audit_event

from .test_auth import assert_error

pytestmark = pytest.mark.asyncio
PATH = "/api/v1/audit-events"


async def seed_events(app, specifications):
    async with app.state.database.session_factory() as db:
        events = [
            AuditEvent(
                id=values.get("id", uuid4()),
                occurred_at=values.get("occurred_at", datetime(2026, 11, 7, 12, tzinfo=UTC)),
                actor_id=values.get("actor_id", uuid4()),
                actor_username=values.get("actor", "admin"),
                action=values.get("action", "payment.created"),
                entity_type=values.get("entity_type", "payment"),
                entity_id=values.get("entity_id", uuid4()),
                entity_title=values.get("title", "Office"),
                changes=values.get("changes", []),
            )
            for values in specifications
        ]
        db.add_all(events)
        await db.commit()
    return events


async def test_audit_requires_admin_and_has_no_mutation_routes(client, create_user, login):
    response = await client.get(PATH)
    assert_error(response, 401, "AUTH_REQUIRED")
    assert response.headers["cache-control"] == "no-store"
    await create_user("ordinary", role="user")
    await create_user()
    await login(client, "ordinary")
    response = await client.get(PATH)
    assert_error(response, 403, "FORBIDDEN")
    assert response.headers["cache-control"] == "no-store"
    auth = await login(client)
    response = await client.get(PATH)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert response.headers["cache-control"] == "no-store"
    assert (
        await client.post(PATH, json={}, headers={"X-CSRF-Token": auth["csrf_token"]})
    ).status_code == 405


async def test_audit_shape_stable_order_and_empty_page_total(app, client, create_user, login):
    await create_user()
    await login(client)
    actor_id, entity_id = uuid4(), uuid4()
    records = await seed_events(
        app,
        [
            {
                "id": UUID(int=index),
                "actor_id": actor_id,
                "entity_id": entity_id,
                "changes": [
                    {
                        "field": "amount",
                        "label": "Сумма",
                        "before": None,
                        "after": "999999999999.99",
                    }
                ],
            }
            for index in range(1, 4)
        ],
    )
    response = await client.get(PATH, params={"limit": 2, "offset": 0})
    assert response.status_code == 200, response.text
    first = response.json()
    assert (first["total"], first["limit"], first["offset"]) == (3, 2, 0)
    assert [item["id"] for item in first["items"]] == [str(records[2].id), str(records[1].id)]
    event = first["items"][0]
    assert set(event) == {"id", "occurred_at", "actor", "action", "entity", "changes"}
    assert event["occurred_at"] == "2026-11-07T12:00:00Z"
    assert event["actor"] == {"id": str(actor_id), "username": "admin"}
    assert event["entity"] == {"type": "payment", "id": str(entity_id), "title": "Office"}
    assert event["changes"][0]["after"] == "999999999999.99"
    second = (await client.get(PATH, params={"limit": 2, "offset": 2})).json()
    assert [item["id"] for item in second["items"]] == [str(records[0].id)]
    beyond = (await client.get(PATH, params={"limit": 2, "offset": 10})).json()
    assert beyond == {"items": [], "total": 3, "limit": 2, "offset": 10}


async def test_audit_dates_are_inclusive_moscow_days_and_bounds_are_independent(
    app, client, create_user, login
):
    await create_user()
    await login(client)
    records = await seed_events(
        app,
        [
            {"occurred_at": datetime(2026, 11, 6, 20, 59, 59, 999999, tzinfo=UTC)},
            {"occurred_at": datetime(2026, 11, 6, 21, tzinfo=UTC)},
            {"occurred_at": datetime(2026, 11, 7, 20, 59, 59, 999999, tzinfo=UTC)},
            {"occurred_at": datetime(2026, 11, 7, 21, tzinfo=UTC)},
        ],
    )
    for params, indices in [
        ({"date_from": "2026-11-07", "date_to": "2026-11-07"}, [2, 1]),
        ({"date_from": "2026-11-07"}, [3, 2, 1]),
        ({"date_to": "2026-11-07"}, [2, 1, 0]),
        ({"date_from": "0001-01-01", "date_to": "9999-12-31"}, [3, 2, 1, 0]),
        ({"date_from": "9999-12-31"}, []),
        ({"date_to": "0001-01-01"}, []),
    ]:
        response = await client.get(PATH, params=params)
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["items"]] == [
            str(records[index].id) for index in indices
        ]


@pytest.mark.parametrize(
    ("timezone_name", "day", "start", "end"),
    [
        (
            "Asia/Tokyo",
            "2026-11-07",
            datetime(2026, 11, 6, 15, tzinfo=UTC),
            datetime(2026, 11, 7, 15, tzinfo=UTC),
        ),
        (
            "America/New_York",
            "2026-11-01",
            datetime(2026, 11, 1, 4, tzinfo=UTC),
            datetime(2026, 11, 2, 5, tzinfo=UTC),
        ),
    ],
)
async def test_audit_dates_follow_configured_timezone_including_dst_day(
    app, client, create_user, login, timezone_name, day, start, end
):
    app.state.settings.app_timezone = timezone_name
    await create_user()
    await login(client)
    records = await seed_events(
        app,
        [
            {"occurred_at": start - timedelta(microseconds=1)},
            {"occurred_at": start},
            {"occurred_at": end - timedelta(microseconds=1)},
            {"occurred_at": end},
        ],
    )
    response = await client.get(PATH, params={"date_from": day, "date_to": day})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert [item["id"] for item in data["items"]] == [str(records[2].id), str(records[1].id)]
    assert all(item["occurred_at"].endswith("Z") for item in data["items"])


async def test_audit_filters_search_names_labels_and_literal_wildcards(
    app, client, create_user, login
):
    await create_user()
    await login(client)
    records = await seed_events(
        app,
        [
            {
                "id": UUID(int=1),
                "actor": "admin_main",
                "title": "Office rent",
                "action": "payment.paid",
            },
            {"id": UUID(int=2), "actor": "ivan", "title": "Storage_100%\\archive"},
            {
                "id": UUID(int=3),
                "actor": "Анна",
                "title": "Аренда",
                "action": "payment.date_changed",
            },
        ],
    )
    for params, indices in [
        ({"actor": "ADMIN", "action": "payment.paid"}, [0]),
        ({"query": "  OFFICE  "}, [0]),
        ({"query": "анНА"}, [2]),
        ({"query": "аренДА"}, [2]),
        ({"query": "исправлена дата"}, [2]),
        ({"query": "создан платёж"}, [1]),
        ({"query": "%"}, [1]),
        ({"query": "_", "actor": "ivan"}, [1]),
        ({"query": "\\"}, [1]),
        ({"actor": "_"}, [0]),
        ({"query": "' OR 1=1 --"}, []),
        ({"action": "user.created"}, []),
    ]:
        response = await client.get(PATH, params=params)
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["items"]] == [
            str(records[index].id) for index in indices
        ]
        assert response.json()["total"] == len(indices)


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-11-08", "date_to": "2026-11-07"},
        {"date_from": "2026-02-30"},
        {"date_to": "2026-11-07T00:00:00Z"},
        {"action": "session.login"},
        {"actor": "a" * 65},
        {"query": "a" * 201},
        {"limit": 101},
        {"limit": 0},
        {"offset": -1},
        {"unexpected": "value"},
    ],
)
async def test_audit_rejects_invalid_or_unknown_filters(client, create_user, login, params):
    await create_user()
    await login(client)
    response = await client.get(PATH, params=params)
    assert_error(response, 422, "VALIDATION_ERROR")
    assert response.json()["error"]["details"]
    assert all(
        set(item) == {"field", "code", "message"} for item in response.json()["error"]["details"]
    )


async def test_record_audit_is_transactional_and_refuses_secret_fields(app, create_user):
    actor = await create_user()
    async with app.state.database.session_factory() as db:
        with pytest.raises(ValueError, match="Unsupported audit change field"):
            record_audit_event(
                db,
                actor=actor,
                action="user.updated",
                entity_type="user",
                entity_id=actor.id,
                entity_title=actor.username,
                changes=[
                    {"field": "password", "label": "Password", "before": None, "after": "secret"}
                ],
            )
        record_audit_event(
            db,
            actor=actor,
            action="password.changed",
            entity_type="account",
            entity_id=actor.id,
            entity_title=actor.username,
        )
        await db.flush()
        async with app.state.database.session_factory() as observer:
            assert await observer.scalar(select(func.count()).select_from(AuditEvent)) == 0
        await db.rollback()
    async with app.state.database.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(AuditEvent)) == 0
