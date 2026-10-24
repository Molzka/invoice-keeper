import math
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete

from app.api.dependencies import (
    CurrentSession,
    DbSession,
    require_allowed_origin,
    require_csrf,
    require_json_request,
)
from app.core.security import csrf_token_for_session
from app.models import UserSession
from app.schemas.auth import AuthResponse, ChangePasswordRequest, LoginRequest
from app.schemas.users import UserRead
from app.services.auth import change_password as change_own_password
from app.services.auth import login as create_login_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(require_json_request), Depends(require_allowed_origin)],
)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> AuthResponse:
    settings = request.app.state.settings
    user, token = await create_login_session(
        db,
        settings,
        payload.username,
        payload.password,
        request.client.host if request.client is not None else "unknown",
        request.cookies.get(settings.session_cookie_name),
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(
        user=UserRead.model_validate(user), csrf_token=csrf_token_for_session(token)
    )


@router.get("/me", response_model=AuthResponse)
async def me(auth: CurrentSession, response: Response) -> AuthResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(
        user=UserRead.model_validate(auth.user), csrf_token=csrf_token_for_session(auth.token)
    )


@router.post(
    "/change-password",
    response_model=AuthResponse,
    dependencies=[Depends(require_json_request), Depends(require_csrf)],
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    auth: CurrentSession,
    db: DbSession,
) -> AuthResponse:
    settings = request.app.state.settings
    user, token, expires_at = await change_own_password(
        db,
        settings,
        auth.user.id,
        auth.session.id,
        auth.token,
        payload.current_password,
        payload.new_password,
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max(0, math.ceil((expires_at - datetime.now(UTC)).total_seconds())),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(
        user=UserRead.model_validate(user), csrf_token=csrf_token_for_session(token)
    )


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
async def logout(request: Request, auth: CurrentSession, db: DbSession) -> Response:
    await db.execute(delete(UserSession).where(UserSession.id == auth.session.id))
    await db.commit()
    settings = request.app.state.settings
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
