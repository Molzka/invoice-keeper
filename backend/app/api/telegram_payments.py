from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import CurrentSession, DbSession, require_csrf, require_json_request
from app.api.mfa import require_bridge
from app.schemas.mfa import EmptyRequest, TelegramSetupResponse, TelegramSetupStatus
from app.schemas.telegram_payments import (
    ClaimPaymentLink,
    ConfirmPaymentLink,
    ConfirmTelegramPayment,
    PreparedTelegramPayment,
    PrepareTelegramPayment,
    TelegramAccepted,
    TelegramPaymentResult,
    TelegramPaymentStatus,
)
from app.services import telegram_payments as service

router = APIRouter(prefix="/auth/telegram-payments", tags=["telegram-payments"])
protected = [Depends(require_csrf), Depends(require_json_request)]
internal_router = APIRouter(
    prefix="/internal/v1/telegram-payments",
    tags=["internal"],
    include_in_schema=False,
    dependencies=[Depends(require_bridge), Depends(require_json_request)],
)


@router.get("", response_model=TelegramPaymentStatus)
async def status(request: Request, db: DbSession, auth: CurrentSession):
    return await service.status(db, request.app.state.settings, auth.user)


@router.post("/setup", response_model=TelegramSetupResponse, dependencies=protected)
async def setup(payload: EmptyRequest, request: Request, db: DbSession, auth: CurrentSession):
    return await service.setup_link(db, request.app.state.settings, auth)


@router.get("/setup/{setup_id}", response_model=TelegramSetupStatus)
async def setup_status(setup_id: UUID, request: Request, db: DbSession, auth: CurrentSession):
    return await service.link_state(db, request.app.state.settings, auth, setup_id)


@router.post("/confirm", response_model=TelegramPaymentStatus, dependencies=protected)
async def confirm_link(
    payload: ConfirmPaymentLink, request: Request, db: DbSession, auth: CurrentSession
):
    return await service.confirm_link(db, request.app.state.settings, auth, payload)


@router.delete("", status_code=204, dependencies=[Depends(require_csrf)])
async def unlink(request: Request, db: DbSession, auth: CurrentSession):
    await service.unlink(db, request.app.state.settings, auth)
    return Response(status_code=204)


@internal_router.post("/claim", response_model=TelegramAccepted)
async def claim(payload: ClaimPaymentLink, request: Request, db: DbSession):
    await service.claim_link(db, request.app.state.settings, payload)
    return TelegramAccepted()


@internal_router.post("/prepare", response_model=PreparedTelegramPayment)
async def prepare(payload: PrepareTelegramPayment, request: Request, db: DbSession):
    return await service.prepare_payment(db, request.app.state.settings, payload)


@internal_router.post("/confirm", response_model=TelegramPaymentResult)
async def confirm(payload: ConfirmTelegramPayment, request: Request, db: DbSession):
    return await service.decision(db, request.app.state.settings, payload)


@internal_router.post("/cancel", response_model=TelegramAccepted)
async def cancel(payload: ConfirmTelegramPayment, request: Request, db: DbSession):
    return await service.decision(db, request.app.state.settings, payload, cancel=True)
