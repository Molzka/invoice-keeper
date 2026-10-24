from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models import User, UserSession
from app.schemas.users import UserCreate, UserUpdate
from app.services.audit import record_audit_event
from app.services.errors import api_error

# Serialize user administration and bootstrap across workers.
ADMIN_LOCK_KEY = 1202638163


async def _lock_and_check_admin(db: AsyncSession, actor_id: UUID) -> User:
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK_KEY})
    actor = await db.scalar(
        select(User)
        .where(User.id == actor_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if actor is None or not actor.is_active or actor.role != "admin":
        raise api_error(403, "FORBIDDEN", "Требуются права администратора")
    return actor


async def create_user(db: AsyncSession, payload: UserCreate, actor_id: UUID) -> User:
    password_hash = await hash_password(payload.password)
    actor = await _lock_and_check_admin(db, actor_id)
    user = User(
        username=payload.username,
        password_hash=password_hash,
        role="user",
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
        record_audit_event(
            db,
            actor=actor,
            action="user.created",
            entity_type="user",
            entity_id=user.id,
            entity_title=user.username,
            changes=[
                {"field": "username", "label": "Логин", "before": None, "after": user.username}
            ],
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise username_taken() from exc
        raise
    return user


async def update_user(db: AsyncSession, user_id: UUID, payload: UserUpdate, actor_id: UUID) -> User:
    changes = payload.model_dump(exclude_unset=True)
    password = changes.pop("password", None)
    password_hash = await hash_password(password) if password is not None else None
    actor = await _lock_and_check_admin(db, actor_id)
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise api_error(404, "USER_NOT_FOUND", "Пользователь не найден")

    if user.role == "admin":
        raise api_error(403, "ADMIN_ACCOUNT_PROTECTED", "Аккаунт администратора защищён")
    if password is not None and await verify_password(password, user.password_hash):
        password_hash = None
    revoke_sessions = password_hash is not None or (
        "username" in changes and changes["username"] != user.username
    )
    previous_username = user.username
    try:
        for field, value in changes.items():
            setattr(user, field, value)
        if password_hash is not None:
            user.password_hash = password_hash
        if revoke_sessions:
            await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
            record_audit_event(
                db,
                actor=actor,
                action="user.updated",
                entity_type="user",
                entity_id=user.id,
                entity_title=user.username,
                changes=[
                    {
                        "field": "username",
                        "label": "Логин",
                        "before": previous_username,
                        "after": user.username,
                    }
                ],
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise username_taken() from exc
        raise
    return user


def username_taken():
    message = "Этот логин уже занят"
    return api_error(
        409,
        "USERNAME_TAKEN",
        message,
        details=[{"field": "username", "code": "USERNAME_TAKEN", "message": message}],
    )


async def delete_user(db: AsyncSession, user_id: UUID, actor_id: UUID) -> None:
    actor = await _lock_and_check_admin(db, actor_id)
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise api_error(404, "USER_NOT_FOUND", "Пользователь не найден")
    if user.role == "admin":
        raise api_error(403, "ADMIN_ACCOUNT_PROTECTED", "Аккаунт администратора защищён")
    record_audit_event(
        db,
        actor=actor,
        action="user.deleted",
        entity_type="user",
        entity_id=user.id,
        entity_title=user.username,
        changes=[{"field": "username", "label": "Логин", "before": user.username, "after": None}],
    )
    await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await db.delete(user)
    await db.commit()
