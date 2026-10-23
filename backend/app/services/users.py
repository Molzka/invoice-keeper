from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import User, UserSession
from app.schemas.users import UserCreate, UserUpdate
from app.services.errors import api_error

# Serialize admin changes across all workers before counting active admins.
ADMIN_LOCK_KEY = 1202638163


async def _lock_and_check_admin(db: AsyncSession, actor_id: UUID) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK_KEY})
    actor = await db.scalar(
        select(User)
        .where(User.id == actor_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if actor is None or not actor.is_active or actor.role != "admin":
        raise api_error(403, "FORBIDDEN", "Требуются права администратора")


async def create_user(db: AsyncSession, payload: UserCreate, actor_id: UUID) -> User:
    password_hash = await hash_password(payload.password)
    await _lock_and_check_admin(db, actor_id)
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=password_hash,
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise api_error(409, "USERNAME_TAKEN", "Этот логин уже занят") from exc
        raise
    return user


async def update_user(db: AsyncSession, user_id: UUID, payload: UserUpdate, actor_id: UUID) -> User:
    changes = payload.model_dump(exclude_unset=True)
    password = changes.pop("password", None)
    password_hash = await hash_password(password) if password is not None else None
    await _lock_and_check_admin(db, actor_id)
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise api_error(404, "USER_NOT_FOUND", "Пользователь не найден")

    remains_active_admin = changes.get("role", user.role) == "admin" and changes.get(
        "is_active", user.is_active
    )
    if user.role == "admin" and user.is_active and not remains_active_admin:
        active_admin_count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
        if active_admin_count <= 1:
            raise api_error(
                409,
                "LAST_ACTIVE_ADMIN",
                "Нельзя отключить или понизить роль последнего активного администратора",
            )

    revoke_sessions = password_hash is not None or any(
        field in changes and changes[field] != getattr(user, field)
        for field in ("role", "is_active")
    )
    for field, value in changes.items():
        setattr(user, field, value)
    if password_hash is not None:
        user.password_hash = password_hash
    if revoke_sessions:
        await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await db.commit()
    return user
