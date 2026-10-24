"""Database-backed MFA. Every one-use decision is serialized by the user row lock."""

import hashlib
import hmac
import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyotp
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.mfa_crypto import (
    code_digest,
    decrypt_secret,
    encrypt_secret,
    fresh_code,
    fresh_recovery_codes,
    matching_totp_step,
    recovery_digest,
)
from app.core.security import (
    create_session_token,
    hash_session_token,
    valid_session_token,
    verify_password,
)
from app.models import User, UserSession
from app.models.mfa import MfaChallenge, MfaRecoveryCode, UserMfa
from app.schemas.mfa import SecurityStatus, TelegramAccount
from app.services.audit import record_audit_event
from app.services.errors import api_error


def credential_hash(user):
    return hashlib.sha256(
        f"{user.username}\0{user.password_hash}\0{user.role}".encode()
    ).hexdigest()


def methods(state):
    if state is None:
        return []
    return (["totp"] if state.totp_secret else []) + (["telegram"] if state.telegram_id else [])


def account(state):
    if state is None or state.telegram_id is None:
        return None
    return TelegramAccount(
        id=str(state.telegram_id),
        username=state.telegram_username,
        display_name=state.telegram_display_name or str(state.telegram_id),
    )


async def security_status(db, settings, user):
    state = await db.get(UserMfa, user.id)
    remaining = await db.scalar(
        select(func.count())
        .select_from(MfaRecoveryCode)
        .where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.consumed_at.is_(None))
    )
    available = []
    if user.role == "user" and settings.mfa_encryption_key:
        available.append("totp")
        if settings.bot_token and settings.bot_internal_token and settings.bot_username:
            available.append("telegram")
    return SecurityStatus(
        can_manage=user.role == "user",
        mfa_enabled=bool(methods(state)),
        methods=methods(state),
        available_methods=available,
        telegram=account(state),
        recovery_codes_remaining=remaining,
    )


async def limit(db, settings, identity, *, send=False, ip=None):
    # This helper commits counters; call before locking or changing security state.
    from app.services.auth import _consume_attempts

    maximum = settings.mfa_send_limit if send else settings.mfa_verification_rate_limit_attempts
    buckets = []
    if ip is not None:
        buckets.append((f"mfa:ip:{ip}", settings.login_rate_limit_ip_attempts))
    buckets.append((f"mfa:{identity}", maximum))
    await _consume_attempts(
        db,
        buckets,
        settings.mfa_rate_window_seconds,
        code="MFA_RATE_LIMITED",
        message="Слишком много попыток. Повторите позже",
    )


async def locked_user(db, user_id, *, session_id=None, session_token=None, manage=False):
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active:
        raise api_error(401, "AUTH_REQUIRED", "Требуется авторизация")
    if session_id is not None:
        conditions = [
            UserSession.id == session_id,
            UserSession.user_id == user.id,
            UserSession.expires_at > datetime.now(UTC),
        ]
        if session_token is not None:
            conditions.append(UserSession.token_hash == hash_session_token(session_token))
        if await db.scalar(select(UserSession.id).where(*conditions)) is None:
            raise api_error(401, "AUTH_REQUIRED", "Требуется авторизация")
    if manage and user.role != "user":
        raise api_error(403, "ADMIN_ACCOUNT_PROTECTED", "Аккаунт администратора защищён")
    return user


def new_challenge(user, settings, purpose, *, session_id=None, setup=False, token=None):
    return MfaChallenge(
        id=uuid4(),
        user_id=user.id,
        session_id=session_id,
        purpose=purpose,
        security_version=user.security_version,
        credential_hash=credential_hash(user),
        token_hash=hash_session_token(token) if token else None,
        attempts=0,
        expires_at=datetime.now(UTC)
        + timedelta(
            seconds=(
                settings.mfa_setup_ttl_seconds if setup else settings.mfa_challenge_ttl_seconds
            )
        ),
    )


def check_challenge(row, user, settings, *, purpose=None):
    if (
        row is None
        or row.consumed_at is not None
        or row.expires_at <= datetime.now(UTC)
        or row.security_version != user.security_version
        or row.credential_hash != credential_hash(user)
        or row.attempts >= settings.mfa_max_attempts
    ):
        raise api_error(
            401 if purpose == "login" else 409,
            "MFA_CHALLENGE_EXPIRED",
            "Подтверждение истекло. Начните заново",
        )
    return row


async def locked_challenge(db, settings, user, purpose, *, identifier=None, session_id=None):
    conditions = [MfaChallenge.user_id == user.id, MfaChallenge.purpose == purpose]
    if identifier is not None:
        conditions.append(MfaChallenge.id == identifier)
    if session_id is not None:
        conditions.append(MfaChallenge.session_id == session_id)
    row = await db.scalar(
        select(MfaChallenge)
        .where(*conditions)
        .order_by(MfaChallenge.created_at.desc(), MfaChallenge.id.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return check_challenge(row, user, settings, purpose=purpose)


async def reject_code(db, settings, row=None):
    if row is not None:
        row.attempts += 1
        if row.attempts >= settings.mfa_max_attempts:
            row.consumed_at = datetime.now(UTC)
    await db.commit()
    raise api_error(422, "MFA_CODE_INVALID", "Неверный или уже использованный код")


async def verify_proof(db, settings, user, state, method, code, *, telegram_challenge=None):
    if not code:
        return False
    now = datetime.now(UTC)
    if method == "totp" and state and state.totp_secret:
        step = matching_totp_step(
            decrypt_secret(settings, state.totp_secret), code, now, state.last_totp_step
        )
        if step is not None:
            state.last_totp_step = step
            return True
    elif method == "telegram" and state and state.telegram_id and telegram_challenge:
        row = telegram_challenge
        if (
            row.code_hash
            and row.code_expires_at
            and row.code_expires_at > now
            and hmac.compare_digest(row.code_hash, code_digest(settings, row.id, code))
        ):
            row.code_hash = None
            return True
    elif method == "recovery" and methods(state):
        row = await db.scalar(
            select(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.user_id == user.id,
                MfaRecoveryCode.code_hash == recovery_digest(code),
                MfaRecoveryCode.consumed_at.is_(None),
            )
            .with_for_update()
        )
        if row is not None:
            row.consumed_at = now
            return True
    return False


async def begin_login(db, settings, user):
    state = await db.get(UserMfa, user.id)
    if not methods(state):
        return None
    token = create_session_token()
    row = new_challenge(user, settings, "login", token=token)
    db.add(row)
    available = methods(state)
    if await db.scalar(
        select(MfaRecoveryCode.id)
        .where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.consumed_at.is_(None))
        .limit(1)
    ):
        available = [*available, "recovery"]
    return token, row, available


async def login_identity(db, token):
    if not valid_session_token(token):
        raise api_error(401, "MFA_CHALLENGE_EXPIRED", "Подтверждение истекло. Начните заново")
    row = await db.scalar(
        select(MfaChallenge).where(
            MfaChallenge.token_hash == hash_session_token(token), MfaChallenge.purpose == "login"
        )
    )
    if row is None:
        raise api_error(401, "MFA_CHALLENGE_EXPIRED", "Подтверждение истекло. Начните заново")
    return row.user_id, row.id


async def complete_login(db, settings, token, method, code, ip):
    user_id, identifier = await login_identity(db, token)
    await limit(db, settings, f"verify:{user_id}", ip=ip)
    user = await locked_user(db, user_id)
    row = await locked_challenge(db, settings, user, "login", identifier=identifier)
    state = await db.get(UserMfa, user.id)
    if not await verify_proof(db, settings, user, state, method, code, telegram_challenge=row):
        await reject_code(db, settings, row)
    row.consumed_at = datetime.now(UTC)
    row.token_hash = None
    new_token = create_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(new_token),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    await db.commit()
    return user, new_token


async def cancel_login(db, settings, token):
    user_id, identifier = await login_identity(db, token)
    user = await locked_user(db, user_id)
    row = await locked_challenge(db, settings, user, "login", identifier=identifier)
    await db.delete(row)
    await db.commit()


def prepare_code(settings, row):
    now = datetime.now(UTC)
    if row.sent_at and (now - row.sent_at).total_seconds() < settings.mfa_resend_seconds:
        remaining = math.ceil(settings.mfa_resend_seconds - (now - row.sent_at).total_seconds())
        raise api_error(
            429,
            "MFA_RESEND_TOO_SOON",
            "Подождите перед повторной отправкой",
            headers={"Retry-After": str(remaining)},
        )
    code = fresh_code()
    row.code_hash = code_digest(settings, row.id, code)
    row.code_expires_at = min(
        row.expires_at, now + timedelta(seconds=settings.mfa_challenge_ttl_seconds)
    )
    row.sent_at = now
    return code


async def deliver(settings, telegram_id, code, purpose):
    from app.delivery.mfa_telegram import send_mfa_code

    try:
        await send_mfa_code(settings, telegram_id, code, purpose)
    except Exception:
        raise api_error(
            503, "MFA_DELIVERY_FAILED", "Не удалось доставить код. Попробуйте позже"
        ) from None


async def send_login_code(db, settings, token, ip):
    user_id, identifier = await login_identity(db, token)
    await limit(db, settings, f"send:{user_id}", send=True, ip=ip)
    user = await locked_user(db, user_id)
    row = await locked_challenge(db, settings, user, "login", identifier=identifier)
    state = await db.get(UserMfa, user.id)
    if state is None or not state.telegram_id:
        raise api_error(409, "MFA_METHOD_UNAVAILABLE", "Этот способ не подключён")
    code = prepare_code(settings, row)
    telegram_id = state.telegram_id
    await db.commit()
    await deliver(settings, telegram_id, code, "login")


async def password_user(db, settings, auth, password, *, sending=False):
    await limit(db, settings, f"{'send' if sending else 'reauth'}:{auth.user.id}", send=sending)
    user = await locked_user(
        db, auth.user.id, session_id=auth.session.id, session_token=auth.token, manage=True
    )
    attempt = None if sending else await reauth_attempt(db, settings, user, auth)
    if not await verify_password(password, user.password_hash):
        if attempt is not None:
            attempt.attempts += 1
            await db.commit()
        raise api_error(422, "CURRENT_PASSWORD_INVALID", "Текущий пароль указан неверно")
    return user


async def reauth_attempt(db, settings, user, auth):
    row = await db.scalar(
        select(MfaChallenge)
        .where(
            MfaChallenge.user_id == user.id,
            MfaChallenge.session_id == auth.session.id,
            MfaChallenge.purpose == "reauth_attempt",
            MfaChallenge.expires_at > datetime.now(UTC),
            MfaChallenge.security_version == user.security_version,
            MfaChallenge.credential_hash == credential_hash(user),
        )
        .order_by(MfaChallenge.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if row is None:
        row = new_challenge(user, settings, "reauth_attempt", session_id=auth.session.id)
        db.add(row)
    return check_challenge(row, user, settings)


async def send_reauth_code(db, settings, auth, password):
    user = await password_user(db, settings, auth, password, sending=True)
    state = await db.get(UserMfa, user.id)
    if state is None or not state.telegram_id:
        raise api_error(409, "MFA_METHOD_UNAVAILABLE", "Этот способ не подключён")
    row = await db.scalar(
        select(MfaChallenge)
        .where(
            MfaChallenge.user_id == user.id,
            MfaChallenge.session_id == auth.session.id,
            MfaChallenge.purpose == "telegram_reauth",
        )
        .order_by(MfaChallenge.created_at.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    if (
        row is None
        or row.expires_at <= now
        or row.consumed_at is not None
        or row.security_version != user.security_version
    ):
        row = new_challenge(user, settings, "telegram_reauth", session_id=auth.session.id)
        db.add(row)
    code = prepare_code(settings, row)
    telegram_id = state.telegram_id
    await db.commit()
    await deliver(settings, telegram_id, code, "reauth")


async def reauthenticate(db, settings, auth, payload):
    user = await password_user(db, settings, auth, payload.password)
    attempt = await reauth_attempt(db, settings, user, auth)
    state = await db.get(UserMfa, user.id)
    if methods(state):
        telegram_row = None
        if payload.method == "telegram":
            telegram_row = await locked_challenge(
                db, settings, user, "telegram_reauth", session_id=auth.session.id
            )
        if not await verify_proof(
            db, settings, user, state, payload.method, payload.code, telegram_challenge=telegram_row
        ):
            await reject_code(db, settings, attempt)
        if telegram_row:
            telegram_row.consumed_at = datetime.now(UTC)
    await db.delete(attempt)
    await db.execute(
        delete(MfaChallenge).where(
            MfaChallenge.session_id == auth.session.id, MfaChallenge.purpose == "grant"
        )
    )
    row = new_challenge(user, settings, "grant", session_id=auth.session.id)
    db.add(row)
    await db.commit()
    return row.expires_at


async def consume_grant(db, settings, auth):
    user = await locked_user(
        db, auth.user.id, session_id=auth.session.id, session_token=auth.token, manage=True
    )
    row = await locked_challenge(db, settings, user, "grant", session_id=auth.session.id)
    row.consumed_at = datetime.now(UTC)
    return user


async def setup_totp(db, settings, auth):
    user = await consume_grant(db, settings, auth)
    secret = pyotp.random_base32()
    row = new_challenge(user, settings, "totp_setup", session_id=auth.session.id, setup=True)
    row.secret_encrypted = encrypt_secret(settings, secret)
    await db.execute(
        delete(MfaChallenge).where(
            MfaChallenge.session_id == auth.session.id, MfaChallenge.purpose == "totp_setup"
        )
    )
    db.add(row)
    await db.commit()
    return {
        "setup_id": row.id,
        "secret": secret,
        "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(
            name=user.username, issuer_name=settings.app_name
        ),
        "expires_at": row.expires_at,
    }


async def replace_recovery(db, user):
    codes = fresh_recovery_codes()
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    db.add_all(
        [MfaRecoveryCode(user_id=user.id, code_hash=recovery_digest(code)) for code in codes]
    )
    return codes


async def finish_change(db, settings, user, auth, action, *, recovery=False):
    # Resolve the unique Telegram binding before any further query can autoflush it.
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise api_error(
            409, "TELEGRAM_ALREADY_LINKED", "Этот Telegram-аккаунт уже подключён"
        ) from None
    codes = await replace_recovery(db, user) if recovery else None
    user.security_version += 1
    await db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == user.id))
    await db.execute(
        delete(UserSession).where(UserSession.user_id == user.id, UserSession.id != auth.session.id)
    )
    record_audit_event(
        db,
        actor=user,
        action=action,
        entity_type="account",
        entity_id=user.id,
        entity_title=user.username,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise api_error(
            409, "TELEGRAM_ALREADY_LINKED", "Этот Telegram-аккаунт уже подключён"
        ) from None
    result = {"security": await security_status(db, settings, user)}
    if codes is not None:
        result["recovery_codes"] = codes
    return result


async def confirm_totp(db, settings, auth, payload):
    await limit(db, settings, f"setup:{auth.user.id}")
    user = await locked_user(
        db, auth.user.id, session_id=auth.session.id, session_token=auth.token, manage=True
    )
    row = await locked_challenge(
        db, settings, user, "totp_setup", identifier=payload.setup_id, session_id=auth.session.id
    )
    secret = decrypt_secret(settings, row.secret_encrypted)
    step = matching_totp_step(secret, payload.code, datetime.now(UTC), -1)
    if step is None:
        await reject_code(db, settings, row)
    state = await db.get(UserMfa, user.id)
    first = not methods(state)
    if state is None:
        state = UserMfa(user_id=user.id)
        db.add(state)
    state.totp_secret, state.last_totp_step = row.secret_encrypted, step
    return await finish_change(
        db,
        settings,
        user,
        auth,
        "account.mfa_enabled" if first else "account.mfa_changed",
        recovery=first,
    )


async def setup_telegram(db, settings, auth):
    user = await consume_grant(db, settings, auth)
    if not all(
        (
            settings.mfa_encryption_key,
            settings.bot_token,
            settings.bot_internal_token,
            settings.bot_username,
        )
    ):
        raise api_error(503, "MFA_UNAVAILABLE", "Подключение Telegram временно недоступно")
    token = create_session_token()
    row = new_challenge(
        user, settings, "telegram_setup", session_id=auth.session.id, setup=True, token=token
    )
    await db.execute(
        delete(MfaChallenge).where(
            MfaChallenge.session_id == auth.session.id, MfaChallenge.purpose == "telegram_setup"
        )
    )
    db.add(row)
    await db.commit()
    return {
        "setup_id": row.id,
        "link": f"https://t.me/{settings.bot_username}?start=mfa_{token}",
        "expires_at": row.expires_at,
    }


async def telegram_setup_status(db, settings, auth, identifier):
    user = await locked_user(
        db, auth.user.id, session_id=auth.session.id, session_token=auth.token, manage=True
    )
    row = await locked_challenge(
        db, settings, user, "telegram_setup", identifier=identifier, session_id=auth.session.id
    )
    return {
        "status": "claimed" if row.telegram_id else "waiting",
        "account": account(row),
        "expires_at": row.expires_at,
    }


async def claim_telegram(db, settings, payload):
    if payload.telegram_id != payload.chat_id:
        raise api_error(400, "MFA_LINK_INVALID", "Откройте ссылку в личном чате")
    found = await db.scalar(
        select(MfaChallenge).where(
            MfaChallenge.token_hash == hash_session_token(payload.token),
            MfaChallenge.purpose == "telegram_setup",
        )
    )
    if found is None:
        raise api_error(400, "MFA_LINK_INVALID", "Ссылка недействительна. Создайте новую на сайте")
    user_id, identifier, session_id = found.user_id, found.id, found.session_id
    await limit(db, settings, f"send:{user_id}", send=True)
    user = await locked_user(db, user_id, session_id=session_id, manage=True)
    row = await locked_challenge(
        db, settings, user, "telegram_setup", identifier=identifier, session_id=session_id
    )
    if row.token_hash != hash_session_token(payload.token) or row.telegram_id is not None:
        raise api_error(400, "MFA_LINK_INVALID", "Ссылка уже использована")
    existing = await db.scalar(
        select(UserMfa.user_id).where(
            UserMfa.telegram_id == payload.telegram_id, UserMfa.user_id != user.id
        )
    )
    if existing is not None:
        raise api_error(409, "TELEGRAM_ALREADY_LINKED", "Этот Telegram-аккаунт уже подключён")
    row.telegram_id, row.telegram_username = payload.telegram_id, payload.username
    row.telegram_display_name = payload.display_name
    row.token_hash = None
    code = prepare_code(settings, row)
    await db.commit()
    await deliver(settings, payload.telegram_id, code, "link")


async def confirm_telegram(db, settings, auth, payload):
    await limit(db, settings, f"setup:{auth.user.id}")
    user = await locked_user(
        db, auth.user.id, session_id=auth.session.id, session_token=auth.token, manage=True
    )
    row = await locked_challenge(
        db,
        settings,
        user,
        "telegram_setup",
        identifier=payload.setup_id,
        session_id=auth.session.id,
    )
    if not (
        row.telegram_id
        and row.code_hash
        and row.code_expires_at
        and row.code_expires_at > datetime.now(UTC)
        and hmac.compare_digest(row.code_hash, code_digest(settings, row.id, payload.code))
    ):
        await reject_code(db, settings, row)
    state = await db.get(UserMfa, user.id)
    first = not methods(state)
    if state is None:
        state = UserMfa(user_id=user.id)
        db.add(state)
    state.telegram_id, state.telegram_username = row.telegram_id, row.telegram_username
    state.telegram_display_name = row.telegram_display_name
    return await finish_change(
        db,
        settings,
        user,
        auth,
        "account.mfa_enabled" if first else "account.mfa_changed",
        recovery=first,
    )


async def remove_factor(db, settings, auth, method=None):
    user = await consume_grant(db, settings, auth)
    state = await db.get(UserMfa, user.id)
    if state is None or not methods(state) or (method is not None and method not in methods(state)):
        raise api_error(409, "MFA_METHOD_UNAVAILABLE", "Этот способ не подключён")
    if method in {None, "totp"}:
        state.totp_secret, state.last_totp_step = None, -1
    if method in {None, "telegram"}:
        state.telegram_id = state.telegram_username = state.telegram_display_name = None
    enabled = bool(methods(state))
    if not enabled:
        await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    return await finish_change(
        db, settings, user, auth, "account.mfa_changed" if enabled else "account.mfa_disabled"
    )


async def regenerate_recovery(db, settings, auth):
    user = await consume_grant(db, settings, auth)
    if not methods(await db.get(UserMfa, user.id)):
        raise api_error(
            409, "MFA_METHOD_UNAVAILABLE", "Сначала подключите дополнительный способ входа"
        )
    return await finish_change(
        db, settings, user, auth, "account.recovery_regenerated", recovery=True
    )
