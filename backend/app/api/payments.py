from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, Security
from fastapi.security import APIKeyCookie

from app.api.dependencies import (
    AdminUser,
    CurrentUser,
    DbSession,
    require_csrf,
    require_json_request,
)
from app.schemas.payments import (
    IsoDate,
    PaymentOccurrenceList,
    PaymentOccurrenceRead,
    PaymentsSummary,
    PaymentStateUpdate,
    RecurringPaymentCreate,
    RecurringPaymentList,
    RecurringPaymentRead,
)
from app.services.payment_summary import get_payments_summary
from app.services.payments import (
    create_recurring_payment,
    get_payment_occurrence,
    list_payment_occurrences,
    list_recurring_payments,
    recurring_payment_data,
    stop_recurring_payment,
    today_in_timezone,
    update_payment_state,
)


def error_response(code: str, message: str) -> dict:
    return {
        "description": message,
        "content": {
            "application/json": {
                "example": {"error": {"code": code, "message": message, "details": []}}
            }
        },
    }


session_cookie = APIKeyCookie(
    name="session_id",
    scheme_name="SessionCookie",
    description="Непрозрачная серверная cookie-сессия",
    auto_error=False,
)
router = APIRouter(
    tags=["payments"],
    dependencies=[Security(session_cookie)],
    responses={
        401: error_response("AUTH_REQUIRED", "Требуется авторизация"),
        422: error_response("VALIDATION_ERROR", "Некорректные данные запроса"),
    },
)
Csrf = Annotated[None, Depends(require_csrf)]


@router.post(
    "/recurring-payments",
    response_model=RecurringPaymentRead,
    status_code=201,
    summary="Создать регулярный платёж",
    dependencies=[Depends(require_json_request)],
    responses={403: error_response("FORBIDDEN", "Требуются права администратора")},
)
async def create_payment(
    payload: RecurringPaymentCreate,
    _admin: AdminUser,
    _csrf: Csrf,
    db: DbSession,
    request: Request,
) -> dict:
    today = today_in_timezone(request.app.state.settings.app_timezone)
    payment = await create_recurring_payment(
        db, payload, today, timezone_name=request.app.state.settings.app_timezone
    )
    return recurring_payment_data(payment, today)


@router.get(
    "/recurring-payments",
    response_model=RecurringPaymentList,
    summary="Список регулярных платежей",
)
async def get_recurring_payments(
    _user: CurrentUser,
    db: DbSession,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    is_active: bool | None = None,
) -> dict:
    today = today_in_timezone(request.app.state.settings.app_timezone)
    items, total = await list_recurring_payments(
        db, today, limit=limit, offset=offset, is_active=is_active
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.delete(
    "/recurring-payments/{payment_id}",
    status_code=204,
    summary="Прекратить регулярный платёж",
    responses={
        403: error_response("FORBIDDEN", "Требуются права администратора"),
        404: error_response("RECURRING_PAYMENT_NOT_FOUND", "Регулярный платёж не найден"),
    },
)
async def delete_recurring_payment(
    payment_id: UUID,
    _admin: AdminUser,
    _csrf: Csrf,
    db: DbSession,
    request: Request,
) -> Response:
    today = today_in_timezone(request.app.state.settings.app_timezone)
    await stop_recurring_payment(
        db, payment_id, today, timezone_name=request.app.state.settings.app_timezone
    )
    return Response(status_code=204)


@router.get(
    "/payment-occurrences",
    response_model=PaymentOccurrenceList,
    summary="Список периодов платежей",
)
async def get_payment_occurrences(
    _user: CurrentUser,
    db: DbSession,
    request: Request,
    date_from: IsoDate | None = None,
    date_to: IsoDate | None = None,
    status: Literal["paid", "unpaid"] | None = None,
    currency: Literal["RUB", "USD", "EUR"] | None = None,
    recurring_payment_id: UUID | None = None,
    is_overdue: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    today = today_in_timezone(request.app.state.settings.app_timezone)
    items, total = await list_payment_occurrences(
        db,
        today,
        date_from=date_from,
        date_to=date_to,
        status=status,
        currency=currency,
        recurring_payment_id=recurring_payment_id,
        is_overdue=is_overdue,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/payment-occurrences/{occurrence_id}",
    response_model=PaymentOccurrenceRead,
    summary="Получить период платежа",
    responses={404: error_response("PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")},
)
async def get_payment_occurrence_by_id(
    occurrence_id: UUID,
    _user: CurrentUser,
    db: DbSession,
    request: Request,
) -> dict:
    today = today_in_timezone(request.app.state.settings.app_timezone)
    return await get_payment_occurrence(db, occurrence_id, today)


@router.patch(
    "/payment-occurrences/{occurrence_id}",
    response_model=PaymentOccurrenceRead,
    summary="Изменить состояние оплаты",
    dependencies=[Depends(require_json_request)],
    responses={404: error_response("PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")},
)
async def patch_payment_occurrence(
    occurrence_id: UUID,
    payload: PaymentStateUpdate,
    _user: CurrentUser,
    _csrf: Csrf,
    db: DbSession,
    request: Request,
) -> dict:
    today = today_in_timezone(request.app.state.settings.app_timezone)
    return await update_payment_state(db, occurrence_id, payload, today)


@router.get(
    "/payments/summary",
    response_model=PaymentsSummary,
    summary="Сводка платежей по сроку оплаты",
    responses={503: error_response("PERIODS_NOT_READY", "История периодов ещё восстанавливается")},
)
async def payments_summary(
    _user: CurrentUser,
    db: DbSession,
    request: Request,
    date_from: IsoDate | None = None,
    date_to: IsoDate | None = None,
) -> dict:
    today = today_in_timezone(request.app.state.settings.app_timezone)
    return await get_payments_summary(
        db,
        today,
        date_from,
        date_to,
        request.app.state.settings.app_timezone,
    )
