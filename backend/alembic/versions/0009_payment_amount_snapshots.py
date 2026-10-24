"""Snapshot period amounts and currencies before allowing price changes.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recurring_payments", sa.Column("amount_effective_from", sa.Date()))
    op.add_column("payment_occurrences", sa.Column("amount", sa.Numeric(14, 2)))
    op.add_column("payment_occurrences", sa.Column("currency", sa.String(3)))
    op.add_column(
        "payment_occurrences",
        sa.Column("amount_is_custom", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Before this revision every period inherited exactly these values from its rule.
    op.execute(
        sa.text(
            "UPDATE payment_occurrences AS occurrence "
            "SET amount = payment.amount, currency = payment.currency "
            "FROM recurring_payments AS payment "
            "WHERE occurrence.recurring_payment_id = payment.id"
        )
    )
    op.alter_column(
        "payment_occurrences", "amount", existing_type=sa.Numeric(14, 2), nullable=False
    )
    op.alter_column("payment_occurrences", "currency", existing_type=sa.String(3), nullable=False)
    op.create_check_constraint(
        op.f("ck_payment_occurrences_amount"),
        "payment_occurrences",
        "amount BETWEEN 0.01 AND 999999999999.99",
    )
    op.create_check_constraint(
        op.f("ck_payment_occurrences_currency"),
        "payment_occurrences",
        "currency IN ('RUB', 'USD', 'EUR')",
    )


def downgrade() -> None:
    # Reverting restores the old inherited-price model; individual prices cannot survive it.
    op.drop_constraint(
        op.f("ck_payment_occurrences_currency"), "payment_occurrences", type_="check"
    )
    op.drop_constraint(op.f("ck_payment_occurrences_amount"), "payment_occurrences", type_="check")
    op.drop_column("payment_occurrences", "amount_is_custom")
    op.drop_column("payment_occurrences", "currency")
    op.drop_column("payment_occurrences", "amount")
    op.drop_column("recurring_payments", "amount_effective_from")
