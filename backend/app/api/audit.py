from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import AdminUser, DbSession
from app.schemas.audit import AuditAction, AuditEventList
from app.schemas.payments import IsoDate
from app.services.audit import list_audit_events

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=AuditEventList, summary="Журнал действий (только администратор)")
async def get_audit_events(
    _admin: AdminUser,
    db: DbSession,
    date_from: IsoDate | None = None,
    date_to: IsoDate | None = None,
    actor: Annotated[str | None, Query(max_length=64)] = None,
    action: AuditAction | None = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return await list_audit_events(
        db,
        date_from=date_from,
        date_to=date_to,
        actor=actor,
        action=action,
        query=query,
        limit=limit,
        offset=offset,
    )
