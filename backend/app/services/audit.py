from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, User
from app.schemas.audit import AUDIT_ACTION_LABELS, SAFE_CHANGE_FIELDS, AuditChange
from app.services.errors import api_error

MOSCOW = ZoneInfo("Europe/Moscow")


def record_audit_event(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: UUID,
    entity_title: str,
    changes: list[dict] | None = None,
) -> AuditEvent:
    """Append explicit safe snapshots in the mutation's transaction; never commit."""
    expected_type = "account" if action == "password.changed" else action.split(".")[0]
    if action not in AUDIT_ACTION_LABELS or entity_type != expected_type:
        raise ValueError("Invalid audit action or entity type")
    safe_changes = []
    for item in changes or []:
        change = AuditChange.model_validate(item)
        if change.field not in SAFE_CHANGE_FIELDS:
            raise ValueError("Unsupported audit change field")
        if change.before != change.after:
            safe_changes.append(change.model_dump())
    event = AuditEvent(
        actor_id=actor.id,
        actor_username=actor.username,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_title=entity_title,
        changes=safe_changes,
    )
    db.add(event)
    return event


def _contains(column, value: str):
    # '%' and '_' from the search box are literal characters, not SQL wildcards.
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


async def list_audit_events(
    db: AsyncSession,
    *,
    date_from: date | None,
    date_to: date | None,
    actor: str | None,
    action: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> dict:
    if date_from is not None and date_to is not None and date_from > date_to:
        message = "Начало диапазона позже его окончания"
        raise api_error(
            422,
            "VALIDATION_ERROR",
            message,
            details=[{"field": "date_to", "code": "INVALID_RANGE", "message": message}],
        )
    filters = []
    if date_from is not None and date_from != date.min:
        filters.append(
            AuditEvent.occurred_at >= datetime.combine(date_from, time.min, MOSCOW).astimezone(UTC)
        )
    if date_to is not None and date_to != date.max:
        filters.append(
            AuditEvent.occurred_at
            < datetime.combine(date_to + timedelta(days=1), time.min, MOSCOW).astimezone(UTC)
        )
    if actor and actor.strip():
        filters.append(_contains(AuditEvent.actor_username, actor.strip()))
    if action is not None:
        filters.append(AuditEvent.action == action)
    if query and query.strip():
        query = query.strip()
        matching_actions = [
            key
            for key, label in AUDIT_ACTION_LABELS.items()
            if query.casefold() in label.casefold()
        ]
        filters.append(
            or_(
                _contains(AuditEvent.actor_username, query),
                _contains(AuditEvent.entity_title, query),
                AuditEvent.action.in_(matching_actions),
            )
        )
    # Count and page share one PostgreSQL statement/snapshot, including an empty
    # page beyond total. Concurrent appends cannot make these two disagree.
    filtered = select(AuditEvent).where(*filters).cte("filtered_audit_events")
    page = (
        select(filtered)
        .order_by(filtered.c.occurred_at.desc(), filtered.c.id.desc())
        .limit(limit)
        .offset(offset)
        .cte("audit_page")
    )
    total = select(func.count().label("total")).select_from(filtered).cte("audit_total")
    rows = (
        (
            await db.execute(
                select(page, total.c.total)
                .select_from(total.outerjoin(page, true()))
                .order_by(page.c.occurred_at.desc(), page.c.id.desc())
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {
                "id": row["id"],
                "occurred_at": row["occurred_at"],
                "actor": {"id": row["actor_id"], "username": row["actor_username"]},
                "action": row["action"],
                "entity": {
                    "type": row["entity_type"],
                    "id": row["entity_id"],
                    "title": row["entity_title"],
                },
                "changes": row["changes"],
            }
            for row in rows
            if row["id"] is not None
        ],
        "total": rows[0]["total"],
        "limit": limit,
        "offset": offset,
    }
