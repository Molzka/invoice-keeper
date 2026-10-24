"""Add recurring payments and payment occurrences.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("first_due_date", sa.Date(), nullable=False),
        sa.Column("periodicity", sa.String(length=16), nullable=False),
        sa.Column("anchor_day", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "title ~ '[^[:space:]]'",
            name=op.f("ck_recurring_payments_title"),
        ),
        sa.CheckConstraint(
            "amount BETWEEN 0.01 AND 999999999999.99",
            name=op.f("ck_recurring_payments_amount"),
        ),
        sa.CheckConstraint(
            "currency IN ('RUB', 'USD', 'EUR')",
            name=op.f("ck_recurring_payments_currency"),
        ),
        sa.CheckConstraint(
            "periodicity = 'monthly'",
            name=op.f("ck_recurring_payments_periodicity"),
        ),
        sa.CheckConstraint(
            "anchor_day BETWEEN 1 AND 31",
            name=op.f("ck_recurring_payments_anchor_day"),
        ),
        sa.CheckConstraint(
            "anchor_day = EXTRACT(DAY FROM first_due_date)::integer",
            name=op.f("ck_recurring_payments_anchor_day_matches_first_due_date"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_payments")),
    )
    op.create_index("ix_recurring_payments_created_at", "recurring_payments", ["created_at"])
    op.create_table(
        "payment_occurrences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recurring_payment_id", sa.Uuid(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="'unpaid'", nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "status IN ('paid', 'unpaid')",
            name=op.f("ck_payment_occurrences_status"),
        ),
        sa.CheckConstraint(
            "(status = 'paid' AND paid_on IS NOT NULL) OR (status = 'unpaid' AND paid_on IS NULL)",
            name=op.f("ck_payment_occurrences_payment_state"),
        ),
        sa.ForeignKeyConstraint(
            ["recurring_payment_id"],
            ["recurring_payments.id"],
            name=op.f("fk_payment_occurrences_recurring_payment_id_recurring_payments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_occurrences")),
        sa.UniqueConstraint(
            "recurring_payment_id",
            "due_date",
            name="uq_payment_occurrences_recurring_payment_due_date",
        ),
    )
    op.create_index(
        "ix_payment_occurrences_due_date_id",
        "payment_occurrences",
        ["due_date", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_occurrences_due_date_id", table_name="payment_occurrences")
    op.drop_table("payment_occurrences")
    op.drop_index("ix_recurring_payments_created_at", table_name="recurring_payments")
    op.drop_table("recurring_payments")
