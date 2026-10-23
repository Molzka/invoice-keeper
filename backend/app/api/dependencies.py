from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_session_token, valid_session_token, verify_csrf_token
from app.db.session import get_db
from app.models import User, UserSession
from app.services.errors import api_error

DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user: User
    session: UserSession
    token: str


def _origin(value: str, *, referer: bool = False) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (not referer and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment))
        ):
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def require_allowed_origin(request: Request) -> None:
    """Validate browser-origin headers; headerless API clients remain supported."""
    value = request.headers.get("origin")
    referer = False
    if value is None:
        value = request.headers.get("referer")
        referer = True
    if value is None:
        return
    source = _origin(value, referer=referer)
    allowed = {_origin(origin) for origin in request.app.state.settings.allowed_origins}
    if source is None or source not in allowed:
        raise api_error(403, "ORIGIN_NOT_ALLOWED", "Источник запроса не разрешён")


def require_json_request(request: Request) -> None:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise api_error(415, "UNSUPPORTED_MEDIA_TYPE", "Требуется формат application/json")


async def get_current_session(request: Request, db: DbSession) -> AuthenticatedSession:
    token = request.cookies.get(request.app.state.settings.session_cookie_name)
    if not valid_session_token(token):
        raise api_error(401, "AUTH_REQUIRED", "Требуется авторизация")
    result = await db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.expires_at > datetime.now(UTC),
            User.is_active.is_(True),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise api_error(401, "AUTH_REQUIRED", "Требуется авторизация")
    session, user = row
    return AuthenticatedSession(user=user, session=session, token=token)


CurrentSession = Annotated[AuthenticatedSession, Depends(get_current_session)]


async def get_current_user(auth: CurrentSession) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise api_error(403, "FORBIDDEN", "Требуются права администратора")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def require_csrf(
    request: Request,
    auth: CurrentSession,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    require_allowed_origin(request)
    if not verify_csrf_token(auth.token, x_csrf_token):
        raise api_error(403, "CSRF_INVALID", "Отсутствует или неверен CSRF-токен")
