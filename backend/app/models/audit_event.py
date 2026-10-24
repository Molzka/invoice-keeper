from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class AuditEvent(Base):
    """Historical snapshots; deleting a user or payment never deletes an event."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('payment.amount_changed', 'payment.terms_changed', 'payment.deleted', 'payment.period_deleted', 'payment.created', 'payment.stopped', 'payment.paid', "
            "'payment.unpaid', 'payment.date_changed', 'user.created', 'user.updated', "
            "'user.deleted', 'password.changed', 'payment.receipt_updated', 'payment.receipt_deleted')",
            name="action",
        ),
        CheckConstraint("entity_type IN ('payment', 'user', 'account')", name="entity_type"),
        CheckConstraint("jsonb_typeof(changes) = 'array'", name="changes_array"),
        Index("ix_audit_events_occurred_at_id", "occurred_at", "id"),
        Index("ix_audit_events_action_occurred_at", "action", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    # Deliberately not foreign keys: both IDs and names are historical evidence.
    actor_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    actor_username: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    entity_title: Mapped[str] = mapped_column(String(200), nullable=False)
    changes: Mapped[list[dict]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
