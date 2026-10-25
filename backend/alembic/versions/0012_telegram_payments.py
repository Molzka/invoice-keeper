"""Independent Telegram payment accounts and one-use payment confirmations."""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

OLD_PURPOSES = (
    "'login', 'grant', 'totp_setup', 'telegram_setup', 'telegram_reauth', 'reauth_attempt'"
)
OLD_ACTIONS = (
    "'payment.created', 'payment.stopped', 'payment.paid', 'payment.unpaid', "
    "'payment.date_changed', 'user.created', 'user.updated', 'user.deleted', "
    "'password.changed', 'payment.receipt_updated', 'payment.receipt_deleted', "
    "'registration.approved', 'registration.rejected', 'account.mfa_enabled', "
    "'account.mfa_disabled', 'account.mfa_changed', 'account.recovery_regenerated', "
    "'payment.amount_changed', 'payment.terms_changed', 'payment.deleted', 'payment.period_deleted', "
    "'account.login', 'account.login_failed', 'account.logout'"
)
NEW_ACTIONS = "'account.telegram_linked', 'account.telegram_unlinked'"


def upgrade():
    op.create_table(
        "telegram_payment_accounts",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(64)),
        sa.Column("display_name", sa.String(128), nullable=False),
    )
    op.create_table(
        "telegram_payment_confirmations",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurrence_id",
            sa.Uuid(),
            sa.ForeignKey("payment_occurrences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'paid', 'cancelled')",
            name=op.f("ck_telegram_payment_confirmations_state"),
        ),
    )
    for column in ("user_id", "expires_at"):
        op.create_index(
            f"ix_telegram_payment_confirmations_{column}",
            "telegram_payment_confirmations",
            [column],
        )
    op.drop_constraint(op.f("ck_mfa_challenges_purpose"), "mfa_challenges", type_="check")
    op.create_check_constraint(
        op.f("ck_mfa_challenges_purpose"),
        "mfa_challenges",
        "purpose IN (" + OLD_PURPOSES + ", 'payment_telegram_setup')",
    )
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"),
        "audit_events",
        "action IN (" + OLD_ACTIONS + ", " + NEW_ACTIONS + ")",
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM telegram_payment_accounts) OR EXISTS "
                "(SELECT 1 FROM telegram_payment_confirmations) OR EXISTS "
                "(SELECT 1 FROM mfa_challenges WHERE purpose='payment_telegram_setup') OR EXISTS "
                "(SELECT 1 FROM audit_events WHERE action IN (" + NEW_ACTIONS + "))"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Cannot downgrade while Telegram payment data exists; export and migrate it first."
        )
    op.drop_table("telegram_payment_confirmations")
    op.drop_table("telegram_payment_accounts")
    op.drop_constraint(op.f("ck_mfa_challenges_purpose"), "mfa_challenges", type_="check")
    op.create_check_constraint(
        op.f("ck_mfa_challenges_purpose"), "mfa_challenges", "purpose IN (" + OLD_PURPOSES + ")"
    )
    op.drop_constraint(op.f("ck_audit_events_action"), "audit_events", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_events_action"), "audit_events", "action IN (" + OLD_ACTIONS + ")"
    )
