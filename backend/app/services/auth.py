import hashlib
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    create_session_token,
    hash_session_token,
    valid_session_token,
    verify_password,
)
from app.models import LoginRateLimit, User, UserSession
from app.services.errors import api_error


async def consume_login_attempt(
    db: AsyncSession, settings: Settings, username: str, ip_address: str
) -> None:
    """Atomically consume both buckets, committing even rejected login attempts."""
    now = datetime.now(UTC)
    window = timedelta(seconds=settings.login_rate_limit_window_seconds)
    buckets = [
        (f"ip:{ip_address}", settings.login_rate_limit_ip_attempts),
        (f"username:{username}", settings.login_rate_limit_attempts),
    ]
    # The same bucket order in every request avoids concurrent lock inversions.
    for identity, limit in buckets:
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        expired = LoginRateLimit.window_started_at <= now - window
        statement = (
            insert(LoginRateLimit)
            .values(key=key, attempts=1, window_started_at=now)
            .on_conflict_do_update(
                index_elements=[LoginRateLimit.key],
                set_={
                    "attempts": case(
                        (expired, 1),
                        else_=func.least(LoginRateLimit.attempts + 1, limit + 1),
                    ),
                    "window_started_at": case(
                        (expired, now), else_=LoginRateLimit.window_started_at
                    ),
                },
            )
            .returning(LoginRateLimit.attempts, LoginRateLimit.window_started_at)
        )
        attempts, window_started_at = (await db.execute(statement)).one()
        if attempts > limit:
            retry_after = max(1, math.ceil((window_started_at + window - now).total_seconds()))
            # A blocked IP must not create buckets for arbitrary new usernames.
            await db.commit()
            raise api_error(
                429,
                "LOGIN_RATE_LIMITED",
                "Слишком много попыток входа. Повторите позже",
                headers={"Retry-After": str(retry_after)},
            )
    await db.commit()


async def login(
    db: AsyncSession,
    settings: Settings,
    username: str,
    password: str,
    ip_address: str,
    previous_token: str | None,
) -> tuple[User, str]:
    await consume_login_attempt(db, settings, username, ip_address)
    user = await db.scalar(select(User).where(User.username == username))
    password_hash = user.password_hash if user is not None else None
    valid_password = await verify_password(password, password_hash)
    if user is None or not valid_password or not user.is_active:
        raise api_error(401, "INVALID_CREDENTIALS", "Неверный логин или пароль")

    # Changes and deletion take the same user row lock before revoking sessions.
    # Refresh after Argon2 so old credentials cannot create a session after a
    # concurrent password or username change commits.
    user = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        user is None
        or not user.is_active
        or user.password_hash != password_hash
        or user.username != username
    ):
        raise api_error(401, "INVALID_CREDENTIALS", "Неверный логин или пароль")

    if valid_session_token(previous_token):
        await db.execute(
            delete(UserSession).where(UserSession.token_hash == hash_session_token(previous_token))
        )
    token = create_session_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    await db.commit()
    return user, token
