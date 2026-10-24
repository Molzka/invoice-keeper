import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import altcha
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password
from app.models import RegistrationChallenge, RegistrationRequest, User
from app.schemas.registration import RegistrationCreate, RegistrationStatus
from app.services.audit import record_audit_event
from app.services.auth import _consume_attempts
from app.services.errors import api_error
from app.services.users import ADMIN_LOCK_KEY, _lock_and_check_admin


def captcha_error():
    return api_error(422, "CAPTCHA_INVALID", "Пройдите проверку защиты от спама ещё раз")


def ip_fingerprint(ip_address: str) -> str:
    return hashlib.sha256(("registration:" + ip_address).encode()).hexdigest()


async def new_challenge(db: AsyncSession, ip_address: str) -> dict:
    await _consume_attempts(
        db,
        [(f"registration-challenge:{ip_address}", 30)],
        900,
        code="REGISTRATION_RATE_LIMITED",
        message="Слишком много проверок. Повторите позже",
    )
    now = datetime.now(UTC)
    await db.execute(delete(RegistrationChallenge).where(RegistrationChallenge.expires_at <= now))
    challenge_id = uuid4()
    verification_key = secrets.token_hex(32)
    expires_at = now + timedelta(minutes=5)
    challenge = altcha.create_challenge(
        algorithm="PBKDF2/SHA-256",
        cost=5000,
        hmac_secret=verification_key,
        expires_at=expires_at,
        data={"id": str(challenge_id)},
    ).to_dict()
    db.add(
        RegistrationChallenge(
            id=challenge_id,
            challenge=challenge,
            verification_key=verification_key,
            ip_hash=ip_fingerprint(ip_address),
            expires_at=expires_at,
        )
    )
    await db.commit()
    return challenge


async def consume_challenge(db: AsyncSession, payload: str, ip_address: str) -> None:
    try:
        decoded = json.loads(base64.b64decode(payload, validate=True))
        challenge = decoded["challenge"]
        identifier = challenge["parameters"]["data"]["id"]
        if not isinstance(identifier, str):
            raise ValueError
        challenge_id = UUID(identifier)
        if set(decoded) != {"challenge", "solution"}:
            raise ValueError
    except (ValueError, TypeError, KeyError, RecursionError):
        raise captcha_error() from None
    row = await db.scalar(
        select(RegistrationChallenge)
        .where(RegistrationChallenge.id == challenge_id)
        .with_for_update()
    )
    if row is None:
        raise captcha_error()
    # Compare the entire server-issued challenge before invoking a KDF. A client
    # cannot choose its cost, memory requirement, expiry or signing algorithm.
    valid = (
        row.expires_at > datetime.now(UTC)
        and row.ip_hash == ip_fingerprint(ip_address)
        and row.challenge == challenge
    )
    verification_key = row.verification_key
    await db.delete(row)
    await db.commit()
    if not valid:
        raise captcha_error()
    try:
        result = await run_in_threadpool(altcha.verify_solution, payload, verification_key)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise captcha_error() from None
    if not result.verified:
        raise captcha_error()


async def submit_request(db: AsyncSession, payload: RegistrationCreate, ip_address: str) -> None:
    await _consume_attempts(
        db,
        [(f"registration-submit:{ip_address}", 10)],
        900,
        code="REGISTRATION_RATE_LIMITED",
        message="Слишком много заявок. Повторите позже",
    )
    await consume_challenge(db, payload.altcha, ip_address)
    # Keep password work identical for new, pending and already-used logins.
    password_hash = await hash_password(payload.password)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK_KEY})
    exists = await db.scalar(select(User.id).where(User.username == payload.username))
    pending = await db.scalar(
        select(RegistrationRequest.id).where(
            RegistrationRequest.username == payload.username,
            RegistrationRequest.status == "pending",
        )
    )
    if exists is None and pending is None:
        db.add(
            RegistrationRequest(
                username=payload.username, password_hash=password_hash, message=payload.message
            )
        )
    await db.commit()


async def list_requests(
    db: AsyncSession, status: RegistrationStatus | None, limit: int, offset: int
) -> dict:
    filters = [] if status is None else [RegistrationRequest.status == status]
    total = await db.scalar(select(func.count()).select_from(RegistrationRequest).where(*filters))
    rows = await db.scalars(
        select(RegistrationRequest)
        .where(*filters)
        .order_by(RegistrationRequest.created_at.desc(), RegistrationRequest.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"items": list(rows), "total": total, "limit": limit, "offset": offset}


async def review_request(
    db: AsyncSession,
    request_id: UUID,
    actor_id: UUID,
    *,
    approve: bool,
    note: str | None = None,
) -> RegistrationRequest:
    actor = await _lock_and_check_admin(db, actor_id)
    row = await db.scalar(
        select(RegistrationRequest)
        .where(RegistrationRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise api_error(404, "REGISTRATION_NOT_FOUND", "Заявка не найдена")
    decision = "approved" if approve else "rejected"
    if row.status != "pending":
        if row.status == decision:
            await db.commit()
            return row
        raise api_error(409, "REGISTRATION_REVIEWED", "Заявка уже рассмотрена. Обновите список")
    if approve:
        existing = await db.scalar(select(User.id).where(User.username == row.username))
        if existing is not None:
            raise api_error(
                409,
                "REGISTRATION_USERNAME_TAKEN",
                "Логин уже занят. Отклоните заявку и попросите сотрудника выбрать другой",
            )
        user = User(
            username=row.username, password_hash=row.password_hash, role="user", is_active=True
        )
        db.add(user)
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
    row.status = decision
    row.password_hash = None
    row.reviewed_at = datetime.now(UTC)
    row.reviewed_by = actor.id
    row.decision_note = (note.strip() or None) if note is not None else None
    record_audit_event(
        db,
        actor=actor,
        action="registration." + decision,
        entity_type="registration",
        entity_id=row.id,
        entity_title=row.username,
        changes=[{"field": "status", "label": "Решение", "before": "pending", "after": decision}],
    )
    await db.commit()
    return row
