import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from app.api.dependencies import (
    CurrentSession,
    DbSession,
    require_allowed_origin,
    require_csrf,
    require_json_request,
)
from app.core.security import csrf_token_for_session, valid_session_token, verify_csrf_token
from app.schemas.auth import AuthResponse
from app.schemas.mfa import (
    ConfirmRequest,
    EmptyRequest,
    ExpiryResponse,
    FactorMethod,
    PasswordRequest,
    ReauthRequest,
    SecurityResult,
    SecurityStatus,
    SendResponse,
    TelegramClaimRequest,
    TelegramSetupResponse,
    TelegramSetupStatus,
    TotpSetupResponse,
    VerifyRequest,
)
from app.schemas.users import UserRead
from app.services import mfa
from app.services.errors import api_error

router = APIRouter(prefix="/auth", tags=["security"])
internal_router = APIRouter(
    prefix="/internal/v1/telegram-auth", tags=["internal"], include_in_schema=False
)
protected = [Depends(require_csrf), Depends(require_json_request)]


def pending_csrf(request: Request, x_csrf_token: Annotated[str | None, Header()] = None):
    require_allowed_origin(request)
    token = request.cookies.get(request.app.state.settings.mfa_cookie_name)
    if not valid_session_token(token):
        raise api_error(401, "MFA_CHALLENGE_EXPIRED", "Подтверждение истекло. Начните заново")
    if not verify_csrf_token(token, x_csrf_token):
        raise api_error(403, "CSRF_FAILED", "Отсутствует или неверен CSRF-токен")
    return token


PendingToken = Annotated[str, Depends(pending_csrf)]


def source_ip(request):
    return request.client.host if request.client else "unknown"


def clear_pending(response, settings):
    response.delete_cookie(
        settings.mfa_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/mfa/verify", response_model=AuthResponse, dependencies=[Depends(require_json_request)]
)
async def verify(
    payload: VerifyRequest, request: Request, response: Response, db: DbSession, token: PendingToken
):
    settings = request.app.state.settings
    user, session_token = await mfa.complete_login(
        db, settings, token, payload.method, payload.code, source_ip(request)
    )
    clear_pending(response, settings)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return AuthResponse(
        user=UserRead.model_validate(user),
        csrf_token=csrf_token_for_session(session_token),
        timezone=settings.app_timezone,
    )


@router.post(
    "/mfa/telegram/send", response_model=SendResponse, dependencies=[Depends(require_json_request)]
)
async def send_login(payload: EmptyRequest, request: Request, db: DbSession, token: PendingToken):
    settings = request.app.state.settings
    await mfa.send_login_code(db, settings, token, source_ip(request))
    return SendResponse(retry_after=settings.mfa_resend_seconds)


@router.post("/mfa/cancel", status_code=204, dependencies=[Depends(require_json_request)])
async def cancel(payload: EmptyRequest, request: Request, db: DbSession, token: PendingToken):
    settings = request.app.state.settings
    await mfa.cancel_login(db, settings, token)
    response = Response(status_code=204)
    clear_pending(response, settings)
    return response


@router.get("/security", response_model=SecurityStatus)
async def security(request: Request, db: DbSession, auth: CurrentSession):
    return await mfa.security_status(db, request.app.state.settings, auth.user)


@router.post("/security/telegram/send-code", response_model=SendResponse, dependencies=protected)
async def send_reauth(
    payload: PasswordRequest, request: Request, db: DbSession, auth: CurrentSession
):
    settings = request.app.state.settings
    await mfa.send_reauth_code(db, settings, auth, payload.password)
    return SendResponse(retry_after=settings.mfa_resend_seconds)


@router.post("/security/reauth", response_model=ExpiryResponse, dependencies=protected)
async def reauth(payload: ReauthRequest, request: Request, db: DbSession, auth: CurrentSession):
    return ExpiryResponse(
        expires_at=await mfa.reauthenticate(db, request.app.state.settings, auth, payload)
    )


@router.post("/security/totp/setup", response_model=TotpSetupResponse, dependencies=protected)
async def totp_setup(payload: EmptyRequest, request: Request, db: DbSession, auth: CurrentSession):
    return await mfa.setup_totp(db, request.app.state.settings, auth)


@router.post(
    "/security/totp/confirm",
    response_model=SecurityResult,
    response_model_exclude_unset=True,
    dependencies=protected,
)
async def totp_confirm(
    payload: ConfirmRequest, request: Request, db: DbSession, auth: CurrentSession
):
    return await mfa.confirm_totp(db, request.app.state.settings, auth, payload)


@router.post(
    "/security/telegram/setup", response_model=TelegramSetupResponse, dependencies=protected
)
async def telegram_setup(
    payload: EmptyRequest, request: Request, db: DbSession, auth: CurrentSession
):
    return await mfa.setup_telegram(db, request.app.state.settings, auth)


@router.get("/security/telegram/setup/{setup_id}", response_model=TelegramSetupStatus)
async def telegram_status(setup_id: UUID, request: Request, db: DbSession, auth: CurrentSession):
    return await mfa.telegram_setup_status(db, request.app.state.settings, auth, setup_id)


@router.post(
    "/security/telegram/confirm",
    response_model=SecurityResult,
    response_model_exclude_unset=True,
    dependencies=protected,
)
async def telegram_confirm(
    payload: ConfirmRequest, request: Request, db: DbSession, auth: CurrentSession
):
    return await mfa.confirm_telegram(db, request.app.state.settings, auth, payload)


@router.post(
    "/security/factors/{method}/remove",
    response_model=SecurityResult,
    response_model_exclude_unset=True,
    dependencies=protected,
)
async def remove(
    method: FactorMethod,
    payload: EmptyRequest,
    request: Request,
    db: DbSession,
    auth: CurrentSession,
):
    return await mfa.remove_factor(db, request.app.state.settings, auth, method)


@router.post(
    "/security/disable",
    response_model=SecurityResult,
    response_model_exclude_unset=True,
    dependencies=protected,
)
async def disable(payload: EmptyRequest, request: Request, db: DbSession, auth: CurrentSession):
    return await mfa.remove_factor(db, request.app.state.settings, auth)


@router.post(
    "/security/recovery/regenerate",
    response_model=SecurityResult,
    response_model_exclude_unset=True,
    dependencies=protected,
)
async def regenerate(payload: EmptyRequest, request: Request, db: DbSession, auth: CurrentSession):
    return await mfa.regenerate_recovery(db, request.app.state.settings, auth)


def require_bridge(request: Request, authorization: Annotated[str | None, Header()] = None):
    secret = request.app.state.settings.bot_internal_token
    expected = f"Bearer {secret.get_secret_value()}" if secret else ""
    if (
        not expected
        or not authorization
        or not hmac.compare_digest(authorization.encode(), expected.encode())
    ):
        raise api_error(403, "FORBIDDEN", "Доступ запрещён")


@internal_router.post(
    "/claim", dependencies=[Depends(require_bridge), Depends(require_json_request)]
)
async def claim(payload: TelegramClaimRequest, request: Request, response: Response, db: DbSession):
    response.headers["Cache-Control"] = "no-store"
    await mfa.claim_telegram(db, request.app.state.settings, payload)
    return {"accepted": True}
