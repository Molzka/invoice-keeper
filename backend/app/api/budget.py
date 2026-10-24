from typing import Annotated

from fastapi import APIRouter, Query, Request, Security

from app.api.dependencies import CurrentUser, DbSession
from app.api.payments import error_response, session_cookie
from app.schemas.budget import PaymentsBudget
from app.services.payment_budget import get_payments_budget
from app.services.payments import today_in_timezone

router = APIRouter(
    tags=["payments"],
    dependencies=[Security(session_cookie)],
    responses={
        401: error_response("AUTH_REQUIRED", "Требуется авторизация"),
        422: error_response("VALIDATION_ERROR", "Некорректные данные запроса"),
        503: error_response("PERIODS_NOT_READY", "История периодов ещё восстанавливается"),
    },
)


@router.get(
    "/payments/budget",
    response_model=PaymentsBudget,
    summary="Бюджет месяца или года с прогнозом будущих платежей",
    description=(
        "Расчёт по сроку оплаты, отдельно для каждой валюты. planned = paid + unpaid + forecast; "
        "overdue входит в unpaid. Прогноз не создаёт периоды и напоминания. "
        "Без month возвращаются все 12 месяцев выбранного года."
    ),
)
async def payments_budget(
    _user: CurrentUser,
    db: DbSession,
    request: Request,
    year: Annotated[int, Query(ge=1, le=9999)],
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> dict:
    timezone_name = request.app.state.settings.app_timezone
    return await get_payments_budget(
        db,
        today=today_in_timezone(timezone_name),
        year=year,
        month=month,
        timezone_name=timezone_name,
    )
