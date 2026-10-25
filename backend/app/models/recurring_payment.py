from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class RecurringPayment(Base):
    __tablename__ = "recurring_payments"
    __table_args__ = (
        CheckConstraint("title ~ '[^[:space:]]'", name="title"),
        CheckConstraint("amount BETWEEN 0.01 AND 999999999999.99", name="amount"),
        CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="currency"),
        CheckConstraint(
            "periodicity IN ('daily', 'weekly', 'monthly', 'yearly', 'once')", name="periodicity"
        ),
        CheckConstraint("recurrence_interval BETWEEN 1 AND 365", name="recurrence_interval"),
        CheckConstraint("anchor_day BETWEEN 1 AND 31", name="anchor_day"),
        CheckConstraint(
            "anchor_day = EXTRACT(DAY FROM first_due_date)::integer",
            name="anchor_day_matches_first_due_date",
        ),
        Index("ix_recurring_payments_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    periodicity: Mapped[str] = mapped_column(String(16), nullable=False)
    recurrence_interval: Mapped[int] = mapped_column(
        SmallInteger, default=1, server_default=text("1"), nullable=False
    )
    anchor_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
