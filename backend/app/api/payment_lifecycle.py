from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import AdminUser, DbSession, require_json_request
from app.api.payments import Csrf
from app.schemas.lifecycle import OneTimePaymentCreate
from app.schemas.payments import PaymentOccurrenceRead
from app.services.payment_lifecycle import (
    archive_payment,
    cancel_occurrence,
    create_one_time_payment,
)
from app.services.payments import today_in_timezone

router = APIRouter(tags=["payments"])


@router.post(
    "/one-time-payments",
    status_code=201,
    response_model=PaymentOccurrenceRead,
    dependencies=[Depends(require_json_request)],
    summary="Создать разовый платёж",
)
async def create_once(
    payload: OneTimePaymentCreate, admin: AdminUser, _csrf: Csrf, db: DbSession, request: Request
) -> dict:
    timezone = request.app.state.settings.app_timezone
    return await create_one_time_payment(
        db, payload, today_in_timezone(timezone), actor=admin, timezone_name=timezone
    )


@router.delete(
    "/payment-occurrences/{occurrence_id}",
    status_code=204,
    summary="Удалить неоплаченный период из обязательств с сохранением истории",
)
async def remove_occurrence(
    occurrence_id: UUID, admin: AdminUser, _csrf: Csrf, db: DbSession
) -> Response:
    await cancel_occurrence(db, occurrence_id, actor=admin)
    return Response(status_code=204)


@router.post(
    "/recurring-payments/{payment_id}/archive",
    status_code=204,
    summary="Удалить правило и неоплаченные обязательства с сохранением истории",
)
async def remove_payment(
    payment_id: UUID, admin: AdminUser, _csrf: Csrf, db: DbSession, request: Request
) -> Response:
    timezone = request.app.state.settings.app_timezone
    await archive_payment(
        db, payment_id, today_in_timezone(timezone), actor=admin, timezone_name=timezone
    )
    return Response(status_code=204)
