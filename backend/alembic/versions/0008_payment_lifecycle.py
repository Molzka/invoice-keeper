"""One-time payments and preserved cancellation history. Revision 0008, after 0007."""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

OLD_ACTIONS = "'payment.created', 'payment.stopped', 'payment.paid', 'payment.unpaid', 'payment.date_changed', 'user.created', 'user.updated', 'user.deleted', 'password.changed', 'payment.receipt_updated', 'payment.receipt_deleted'"
NEW_ACTIONS = (
    OLD_ACTIONS
    + ", 'payment.amount_changed', 'payment.terms_changed', 'payment.deleted', 'payment.period_deleted'"
)


def upgrade():
    op.add_column(
        "recurring_payments",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "payment_occurrences",
        sa.Column("is_cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_constraint(
        op.f("ck_recurring_payments_periodicity"), "recurring_payments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_recurring_payments_periodicity"),
        "recurring_payments",
        "periodicity IN ('monthly', 'once')",
    )
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"), "audit_events", "action IN (" + NEW_ACTIONS + ")"
    )


def downgrade():
    # Refuse a lossy downgrade rather than dropping one-time obligations or their evidence.
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM recurring_payments WHERE periodicity='once' OR is_archived) OR EXISTS (SELECT 1 FROM payment_occurrences WHERE is_cancelled) OR EXISTS (SELECT 1 FROM audit_events WHERE action NOT IN ("
            + OLD_ACTIONS
            + "))"
        )
    ).scalar():
        raise RuntimeError(
            "Cannot downgrade while lifecycle data exists; export and migrate it explicitly."
        )
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"), "audit_events", "action IN (" + OLD_ACTIONS + ")"
    )
    op.drop_constraint(
        op.f("ck_recurring_payments_periodicity"), "recurring_payments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_recurring_payments_periodicity"), "recurring_payments", "periodicity = 'monthly'"
    )
    op.drop_column("payment_occurrences", "is_cancelled")
    op.drop_column("recurring_payments", "is_archived")
