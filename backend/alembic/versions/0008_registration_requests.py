"""Moderated employee requests and one-time local CAPTCHA challenges.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = (
    "'payment.created', 'payment.stopped', 'payment.paid', 'payment.unpaid', "
    "'payment.date_changed', 'user.created', 'user.updated', 'user.deleted', "
    "'password.changed', 'payment.receipt_updated', 'payment.receipt_deleted'"
)
NEW_ACTIONS = (
    "'registration.approved', 'registration.rejected', 'account.mfa_enabled', "
    "'account.mfa_disabled', 'account.mfa_changed', 'account.recovery_regenerated'"
)


def upgrade() -> None:
    op.create_table(
        "registration_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.Uuid()),
        sa.Column("decision_note", sa.String(300)),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_registration_requests_status"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND password_hash IS NOT NULL AND reviewed_at IS NULL) OR "
            "(status <> 'pending' AND password_hash IS NULL AND reviewed_at IS NOT NULL)",
            name=op.f("ck_registration_requests_review_state"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_registration_requests_reviewed_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_requests")),
    )
    op.create_index(
        "uq_registration_requests_pending_username",
        "registration_requests",
        ["username"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_registration_requests_status_created_at",
        "registration_requests",
        ["status", "created_at"],
    )
    op.create_table(
        "registration_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge", postgresql.JSONB(), nullable=False),
        sa.Column("verification_key", sa.Text(), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_challenges")),
    )
    op.create_index(
        "ix_registration_challenges_expires_at", "registration_challenges", ["expires_at"]
    )
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"), "audit_events", f"action IN ({OLD_ACTIONS}, {NEW_ACTIONS})"
    )
    op.drop_constraint(op.f("ck_audit_events_entity_type"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_entity_type"),
        "audit_events",
        "entity_type IN ('payment', 'user', 'account', 'registration')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM registration_requests)")
    ) or connection.scalar(
        sa.text(f"SELECT EXISTS (SELECT 1 FROM audit_events WHERE action IN ({NEW_ACTIONS}))")
    ):
        raise RuntimeError("Downgrade would discard registration or security audit data")
    op.drop_table("registration_challenges")
    op.drop_table("registration_requests")
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"), "audit_events", f"action IN ({OLD_ACTIONS})"
    )
    op.drop_constraint(op.f("ck_audit_events_entity_type"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_entity_type"),
        "audit_events",
        "entity_type IN ('payment', 'user', 'account')",
    )
