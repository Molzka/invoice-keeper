from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import AdminUser, DbSession, require_csrf, require_json_request
from app.schemas.registration import (
    RegistrationAccepted,
    RegistrationApprove,
    RegistrationCreate,
    RegistrationList,
    RegistrationRead,
    RegistrationReject,
    RegistrationStatus,
)
from app.services import registration

router = APIRouter(prefix="/registration", tags=["registration"])


@router.get("/challenge")
async def challenge(request: Request, db: DbSession) -> dict:
    return await registration.new_challenge(
        db, request.client.host if request.client is not None else "unknown"
    )


@router.post(
    "/requests",
    response_model=RegistrationAccepted,
    status_code=202,
    dependencies=[Depends(require_json_request)],
)
async def submit(payload: RegistrationCreate, request: Request, db: DbSession):
    await registration.submit_request(
        db, payload, request.client.host if request.client is not None else "unknown"
    )
    return RegistrationAccepted()


@router.get("/requests", response_model=RegistrationList)
async def list_requests(
    admin: AdminUser,
    db: DbSession,
    status: RegistrationStatus | None = "pending",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await registration.list_requests(db, status, limit, offset)


@router.post(
    "/requests/{request_id}/approve",
    response_model=RegistrationRead,
    dependencies=[Depends(require_json_request), Depends(require_csrf)],
)
async def approve(request_id: UUID, payload: RegistrationApprove, admin: AdminUser, db: DbSession):
    return await registration.review_request(db, request_id, admin.id, approve=True)


@router.post(
    "/requests/{request_id}/reject",
    response_model=RegistrationRead,
    dependencies=[Depends(require_json_request), Depends(require_csrf)],
)
async def reject(request_id: UUID, payload: RegistrationReject, admin: AdminUser, db: DbSession):
    return await registration.review_request(
        db, request_id, admin.id, approve=False, note=payload.note
    )
