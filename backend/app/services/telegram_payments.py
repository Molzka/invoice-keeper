from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.security import create_session_token, hash_session_token
from app.delivery.locking import lock_payments
from app.models import MfaChallenge, TelegramPaymentAccount, TelegramPaymentConfirmation, User
from app.schemas.payments import PaymentStateUpdate
from app.services import mfa
from app.services.audit import record_audit_event
from app.services.auth import _consume_attempts
from app.services.errors import api_error
from app.services.payments import get_payment_occurrence, today_in_timezone, update_payment_state

SETUP = "payment_telegram_setup"


def configured_chat(settings):
    try:
        value = int(settings.chat_id or "")
        return value if value != 0 else None
    except ValueError:
        return None


def account_data(row):
    return (
        None
        if row is None
        else {
            "id": str(row.telegram_id),
            "username": row.username,
            "display_name": row.display_name,
        }
    )


async def status(db, settings, user):
    row = await db.get(TelegramPaymentAccount, user.id) if user.role == "user" else None
    account = account_data(row)
    if (
        user.role == "admin"
        and settings.admin_telegram_id
        and user.username == (settings.admin_username or "").strip().lower()
    ):
        account = {
            "id": str(settings.admin_telegram_id),
            "username": None,
            "display_name": user.username,
        }
    return {
        "available": bool(
            settings.bot_username and settings.bot_internal_token and configured_chat(settings)
        ),
        "can_manage": user.role == "user",
        "account": account,
    }


async def setup_link(db, settings, auth):
    user = await mfa.consume_grant(db, settings, auth)
    if not (await status(db, settings, user))["available"]:
        raise api_error(503, "TELEGRAM_PAYMENTS_UNAVAILABLE", "Оплата в Telegram ещё не настроена")
    token = create_session_token()
    await db.execute(
        delete(MfaChallenge).where(MfaChallenge.user_id == user.id, MfaChallenge.purpose == SETUP)
    )
    row = mfa.new_challenge(
        user, settings, SETUP, session_id=auth.session.id, setup=True, token=token
    )
    db.add(row)
    await db.commit()
    return {
        "setup_id": row.id,
        "link": f"https://t.me/{settings.bot_username}?start=paylink_{token}",
        "expires_at": row.expires_at,
    }


async def claim_link(db, settings, payload):
    if payload.telegram_id != payload.chat_id:
        raise api_error(400, "TELEGRAM_LINK_INVALID", "Откройте ссылку в личном чате с ботом")
    await _consume_attempts(
        db,
        [(f"telegram-link:{payload.telegram_id}", 30)],
        900,
        code="TELEGRAM_RATE_LIMITED",
        message="Слишком много попыток. Повторите позже",
    )
    found = await db.scalar(
        select(MfaChallenge).where(
            MfaChallenge.token_hash == hash_session_token(payload.token),
            MfaChallenge.purpose == SETUP,
        )
    )
    if found is None:
        raise api_error(409, "TELEGRAM_LINK_INVALID", "Ссылка истекла или уже использована")
    user = await mfa.locked_user(db, found.user_id, session_id=found.session_id, manage=True)
    row = await mfa.locked_challenge(db, settings, user, SETUP, identifier=found.id)
    if row.telegram_id is not None:
        raise api_error(409, "TELEGRAM_LINK_USED", "Ссылка уже открыта. Создайте новую на сайте")
    if payload.telegram_id == settings.admin_telegram_id:
        raise api_error(
            403, "ADMIN_ACCOUNT_PROTECTED", "Этот Telegram задан администратору в конфигурации"
        )
    row.telegram_id, row.telegram_username = payload.telegram_id, payload.username
    row.telegram_display_name = payload.display_name
    await db.commit()


async def link_state(db, settings, auth, setup_id):
    user = await mfa.locked_user(
        db, auth.user.id, session_id=auth.session.id, session_token=auth.token, manage=True
    )
    row = await mfa.locked_challenge(
        db, settings, user, SETUP, identifier=setup_id, session_id=auth.session.id
    )
    return {
        "status": "claimed" if row.telegram_id else "waiting",
        "account": mfa.account(row),
        "expires_at": row.expires_at,
    }


async def confirm_link(db, settings, auth, payload):
    user = await mfa.locked_user(
        db, auth.user.id, session_id=auth.session.id, session_token=auth.token, manage=True
    )
    row = await mfa.locked_challenge(
        db, settings, user, SETUP, identifier=payload.setup_id, session_id=auth.session.id
    )
    if row.telegram_id is None or str(row.telegram_id) != payload.telegram_id:
        raise api_error(409, "TELEGRAM_LINK_INVALID", "Сначала проверьте аккаунт, открывший ссылку")
    if row.telegram_id == settings.admin_telegram_id:
        raise api_error(403, "ADMIN_ACCOUNT_PROTECTED", "Аккаунт администратора защищён")
    await lock_payments(db)
    account = await db.get(TelegramPaymentAccount, user.id)
    if account is None:
        account = TelegramPaymentAccount(user_id=user.id)
        db.add(account)
    account.telegram_id, account.username = row.telegram_id, row.telegram_username
    account.display_name = row.telegram_display_name or str(row.telegram_id)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise api_error(
            409, "TELEGRAM_ALREADY_LINKED", "Этот Telegram уже связан с другим пользователем"
        ) from None
    await db.execute(
        delete(TelegramPaymentConfirmation).where(TelegramPaymentConfirmation.user_id == user.id)
    )
    await db.delete(row)
    record_audit_event(
        db,
        actor=user,
        action="account.telegram_linked",
        entity_type="account",
        entity_id=user.id,
        entity_title=user.username,
    )
    await db.commit()
    return await status(db, settings, user)


async def unlink(db, settings, auth):
    user = await mfa.consume_grant(db, settings, auth)
    await lock_payments(db)
    removed = await db.scalar(
        delete(TelegramPaymentAccount)
        .where(TelegramPaymentAccount.user_id == user.id)
        .returning(TelegramPaymentAccount.user_id)
    )
    await db.execute(
        delete(TelegramPaymentConfirmation).where(TelegramPaymentConfirmation.user_id == user.id)
    )
    await db.execute(
        delete(MfaChallenge).where(MfaChallenge.user_id == user.id, MfaChallenge.purpose == SETUP)
    )
    if removed is not None:
        record_audit_event(
            db,
            actor=user,
            action="account.telegram_unlinked",
            entity_type="account",
            entity_id=user.id,
            entity_title=user.username,
        )
    await db.commit()


async def payment_actor(db, settings, payload):
    if configured_chat(settings) is None or payload.chat_id != configured_chat(settings):
        raise api_error(403, "TELEGRAM_CHAT_DENIED", "Оплата доступна только в рабочем чате")
    await _consume_attempts(
        db,
        [(f"telegram-payments:{payload.telegram_id}", 60)],
        60,
        code="TELEGRAM_RATE_LIMITED",
        message="Слишком много действий. Повторите позже",
    )
    query = select(User).where(User.is_active.is_(True))
    if payload.telegram_id == settings.admin_telegram_id:
        if await db.scalar(
            select(TelegramPaymentAccount.user_id).where(
                TelegramPaymentAccount.telegram_id == payload.telegram_id
            )
        ):
            raise api_error(
                403,
                "TELEGRAM_ID_CONFLICT",
                "Администратор должен устранить конфликт привязки Telegram",
            )
        query = query.where(
            User.role == "admin", User.username == (settings.admin_username or "").strip().lower()
        )
    else:
        query = query.join(TelegramPaymentAccount, TelegramPaymentAccount.user_id == User.id).where(
            TelegramPaymentAccount.telegram_id == payload.telegram_id,
            User.role == "user",
        )
    user = await db.scalar(query.with_for_update(of=User).execution_options(populate_existing=True))
    if user is not None and payload.telegram_id != settings.admin_telegram_id:
        # The join may have read a binding before waiting for an unlink's user lock.
        linked_id = await db.scalar(
            select(TelegramPaymentAccount.telegram_id).where(
                TelegramPaymentAccount.user_id == user.id
            )
        )
        if linked_id != payload.telegram_id:
            user = None
    if user is None:
        raise api_error(
            403,
            "TELEGRAM_ACCOUNT_REQUIRED",
            "Привяжите Telegram в разделе «Безопасность → Оплата в Telegram» веб-панели",
        )
    await lock_payments(db)
    return user


async def prepare_payment(db, settings, payload):
    user = await payment_actor(db, settings, payload)
    today = today_in_timezone(settings.app_timezone)
    item = await get_payment_occurrence(db, payload.occurrence_id, today)
    if item["is_cancelled"]:
        raise api_error(409, "PAYMENT_CANCELLED", "Этот период удалён из обязательств")
    if item["status"] == "paid":
        raise api_error(409, "PAYMENT_ALREADY_PAID", "Этот период уже оплачен. Обновите карточку")
    now = datetime.now(UTC)
    await db.execute(
        delete(TelegramPaymentConfirmation).where(TelegramPaymentConfirmation.expires_at <= now)
    )
    token = create_session_token()
    row = TelegramPaymentConfirmation(
        token_hash=hash_session_token(token),
        user_id=user.id,
        telegram_id=payload.telegram_id,
        chat_id=payload.chat_id,
        occurrence_id=payload.occurrence_id,
        amount=Decimal(item["amount"]),
        currency=item["currency"],
        paid_on=today,
        security_version=user.security_version,
        expires_at=now + timedelta(minutes=5),
    )
    db.add(row)
    await db.commit()
    return {
        "token": token,
        "payment": item,
        "paid_on": today,
        "timezone": settings.app_timezone,
        "expires_at": row.expires_at,
    }


async def decision(db, settings, payload, *, cancel=False):
    user = await payment_actor(db, settings, payload)
    row = await db.scalar(
        select(TelegramPaymentConfirmation)
        .where(
            TelegramPaymentConfirmation.token_hash == hash_session_token(payload.token),
            TelegramPaymentConfirmation.user_id == user.id,
            TelegramPaymentConfirmation.telegram_id == payload.telegram_id,
            TelegramPaymentConfirmation.chat_id == payload.chat_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.expires_at <= datetime.now(UTC)
        or row.security_version != user.security_version
    ):
        raise api_error(
            409, "TELEGRAM_CONFIRMATION_EXPIRED", "Подтверждение истекло. Нажмите «Оплачено» заново"
        )
    if cancel:
        if row.state == "pending":
            row.state = "cancelled"
        await db.commit()
        return {"accepted": True}
    if row.state == "cancelled":
        raise api_error(409, "TELEGRAM_CONFIRMATION_EXPIRED", "Подтверждение отменено")
    today = today_in_timezone(settings.app_timezone)
    item = await get_payment_occurrence(db, row.occurrence_id, today)
    if row.state == "paid":
        await db.commit()
        return {"outcome": "already_processed", "payment": item}
    if item["is_cancelled"]:
        raise api_error(409, "PAYMENT_CANCELLED", "Этот период удалён из обязательств")
    if item["amount"] != format(row.amount, ".2f") or item["currency"] != row.currency:
        raise api_error(
            409,
            "TELEGRAM_PAYMENT_CHANGED",
            "Сумма или валюта изменились. Нажмите «Оплачено» заново",
        )
    outcome = "already_paid"
    if item["status"] != "paid":
        item = await update_payment_state(
            db,
            row.occurrence_id,
            PaymentStateUpdate(status="paid", paid_on=row.paid_on.isoformat()),
            today,
            actor=user,
            commit=False,
        )
        outcome = "paid"
    row.state = "paid"
    await db.commit()
    return {"outcome": outcome, "payment": item}
