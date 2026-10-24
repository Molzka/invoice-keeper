"""Owned outbox schema, integrated by revision 0003.

The table joins the shared model metadata; production uses 0003's DDL snapshot.
No schema creation takes place at application or worker startup.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    text,
)

from app.db.base import Base

# Kept as an alias for the integration contract; the payment FKs share Base.metadata.
delivery_metadata = Base.metadata
deliveries = Table(
    "reminder_deliveries",
    delivery_metadata,
    Column("id", Uuid, primary_key=True),
    Column("payment_id", Uuid, nullable=False),
    Column("occurrence_id", Uuid, nullable=False),
    Column("scheduled_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False, server_default="pending"),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("attempt_id", Uuid),
    Column("lease_until", DateTime(timezone=True)),
    Column("sent_at", DateTime(timezone=True)),
    Column("telegram_message_id", BigInteger),
    Column("last_error_code", String(64)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("occurrence_id", name="uq_reminder_deliveries_occurrence_id"),
    ForeignKeyConstraint(
        ["payment_id"],
        ["recurring_payments.id"],
        name="fk_reminder_deliveries_payment_id_recurring_payments",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["occurrence_id"],
        ["payment_occurrences.id"],
        name="fk_reminder_deliveries_occurrence_id_payment_occurrences",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "status IN ('pending', 'in_flight', 'retry', 'sent', 'unknown', 'cancelled', 'failed')",
        name="ck_reminder_deliveries_status",
    ),
    CheckConstraint("attempt_count >= 0", name="ck_reminder_deliveries_attempt_count"),
    CheckConstraint(
        "status != 'in_flight' OR (attempt_id IS NOT NULL AND lease_until IS NOT NULL)",
        name="ck_reminder_deliveries_claim",
    ),
    CheckConstraint(
        "status != 'sent' OR (sent_at IS NOT NULL AND telegram_message_id IS NOT NULL AND telegram_message_id > 0)",
        name="ck_reminder_deliveries_confirmed",
    ),
    Index("ix_reminder_deliveries_ready", "status", "available_at"),
    Index("ix_reminder_deliveries_payment_id", "payment_id"),
)
