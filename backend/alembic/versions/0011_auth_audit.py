"""Record authentication events, including attempts for unknown accounts."""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

OLD_ACTIONS = (
    "'payment.created', 'payment.stopped', 'payment.paid', 'payment.unpaid', "
    "'payment.date_changed', 'user.created', 'user.updated', 'user.deleted', "
    "'password.changed', 'payment.receipt_updated', 'payment.receipt_deleted', "
    "'registration.approved', 'registration.rejected', 'account.mfa_enabled', "
    "'account.mfa_disabled', 'account.mfa_changed', 'account.recovery_regenerated', "
    "'payment.amount_changed', 'payment.terms_changed', 'payment.deleted', 'payment.period_deleted'"
)
AUTH_ACTIONS = "'account.login', 'account.login_failed', 'account.logout'"


def upgrade():
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"),
        "audit_events",
        "action IN (" + OLD_ACTIONS + ", " + AUTH_ACTIONS + ")",
    )
    for column in ("actor_id", "entity_id"):
        op.alter_column("audit_events", column, existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        op.f("ck_audit_events_identified_actor"),
        "audit_events",
        "(actor_id IS NOT NULL AND entity_id IS NOT NULL) OR action = 'account.login_failed'",
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM audit_events WHERE action IN (" + AUTH_ACTIONS + "))"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Cannot downgrade while authentication history exists; export it first.")
    op.drop_constraint(op.f("ck_audit_events_identified_actor"), "audit_events", type_="check")
    for column in ("actor_id", "entity_id"):
        op.alter_column("audit_events", column, existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"), "audit_events", "action IN (" + OLD_ACTIONS + ")"
    )
