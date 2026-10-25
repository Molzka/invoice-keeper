"""Configurable recurring payment intervals. Revision 0013, after 0012."""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "recurring_payments",
        sa.Column(
            "recurrence_interval",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        op.f("ck_recurring_payments_recurrence_interval"),
        "recurring_payments",
        "recurrence_interval BETWEEN 1 AND 365",
    )
    op.drop_constraint(
        op.f("ck_recurring_payments_periodicity"), "recurring_payments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_recurring_payments_periodicity"),
        "recurring_payments",
        "periodicity IN ('daily', 'weekly', 'monthly', 'yearly', 'once')",
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM recurring_payments "
                "WHERE periodicity NOT IN ('monthly', 'once') OR recurrence_interval <> 1)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Cannot downgrade while custom recurrence schedules exist.")
    op.drop_constraint(
        op.f("ck_recurring_payments_periodicity"), "recurring_payments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_recurring_payments_periodicity"),
        "recurring_payments",
        "periodicity IN ('monthly', 'once')",
    )
    op.drop_constraint(
        op.f("ck_recurring_payments_recurrence_interval"), "recurring_payments", type_="check"
    )
    op.drop_column("recurring_payments", "recurrence_interval")
