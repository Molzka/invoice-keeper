"""Owned outbox schema, included by participant 2's forthcoming revision 0003.

Separate metadata keeps current head 0002 valid until the payment migration lands.
At integration, Alembic's target_metadata must include `delivery_metadata` as well.
No schema creation takes place at application or worker startup.
"""

from alembic.operations import Operations, ops
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    text,
)

delivery_metadata = MetaData()
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


def create_delivery_schema(op: Operations) -> None:
    """Call from 0003.upgrade(), after creating the payment tables."""
    op.invoke(ops.CreateTableOp.from_table(deliveries))
    for index in sorted(deliveries.indexes, key=lambda item: item.name):
        op.invoke(ops.CreateIndexOp.from_index(index))


def drop_delivery_schema(op: Operations) -> None:
    """Call first in 0003.downgrade(), before dropping payment tables."""
    op.drop_table(deliveries.name)
