from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentOccurrence(Base):
    __tablename__ = "payment_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "recurring_payment_id",
            "due_date",
            name="uq_payment_occurrences_recurring_payment_due_date",
        ),
        CheckConstraint("status IN ('paid', 'unpaid')", name="status"),
        CheckConstraint(
            "(status = 'paid' AND paid_on IS NOT NULL) OR (status = 'unpaid' AND paid_on IS NULL)",
            name="payment_state",
        ),
        Index("ix_payment_occurrences_due_date_id", "due_date", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    recurring_payment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("recurring_payments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="unpaid", server_default=text("'unpaid'"), nullable=False
    )
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
