from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TelegramPaymentAccount(Base):
    __tablename__ = "telegram_payment_accounts"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128))


class TelegramPaymentConfirmation(Base):
    __tablename__ = "telegram_payment_confirmations"
    __table_args__ = (CheckConstraint("state IN ('pending', 'paid', 'cancelled')", name="state"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    occurrence_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("payment_occurrences.id", ondelete="CASCADE")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    paid_on: Mapped[date] = mapped_column(Date)
    security_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(10), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
