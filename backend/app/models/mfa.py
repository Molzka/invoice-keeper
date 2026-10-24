from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class UserMfa(Base):
    __tablename__ = "user_mfa"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    totp_secret: Mapped[str | None] = mapped_column(Text)
    last_totp_step: Mapped[int] = mapped_column(BigInteger, default=-1, server_default=text("-1"))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    telegram_display_name: Mapped[str | None] = mapped_column(String(128))


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('login', 'grant', 'totp_setup', 'telegram_setup', 'telegram_reauth', 'reauth_attempt')",
            name="purpose",
        ),
        CheckConstraint("attempts >= 0", name="attempts"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("user_sessions.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(24))
    security_version: Mapped[int] = mapped_column(Integer)
    credential_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
    code_hash: Mapped[str | None] = mapped_column(String(64))
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    telegram_display_name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MfaRecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
