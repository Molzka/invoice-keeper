"""Persist action audit snapshots without cascading user/payment deletion.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_username", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("entity_title", sa.String(length=200), nullable=False),
        sa.Column(
            "changes", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('payment.created', 'payment.stopped', 'payment.paid', "
            "'payment.unpaid', 'payment.date_changed', 'user.created', 'user.updated', "
            "'user.deleted', 'password.changed', 'payment.receipt_updated', 'payment.receipt_deleted')",
            name=op.f("ck_audit_events_action"),
        ),
        sa.CheckConstraint(
            "entity_type IN ('payment', 'user', 'account')",
            name=op.f("ck_audit_events_entity_type"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changes) = 'array'", name=op.f("ck_audit_events_changes_array")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_occurred_at_id", "audit_events", ["occurred_at", "id"])
    op.create_index("ix_audit_events_action_occurred_at", "audit_events", ["action", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_action_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at_id", table_name="audit_events")
    op.drop_table("audit_events")
