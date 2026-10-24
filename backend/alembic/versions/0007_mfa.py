"""Add voluntary MFA and short-lived, single-use authentication challenges."""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("security_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "user_mfa",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("totp_secret", sa.Text()),
        sa.Column("last_totp_step", sa.BigInteger(), nullable=False, server_default="-1"),
        sa.Column("telegram_id", sa.BigInteger(), unique=True),
        sa.Column("telegram_username", sa.String(64)),
        sa.Column("telegram_display_name", sa.String(128)),
    )
    op.create_table(
        "mfa_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("user_sessions.id", ondelete="CASCADE")),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True),
        sa.Column("secret_encrypted", sa.Text()),
        sa.Column("code_hash", sa.String(64)),
        sa.Column("code_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("telegram_id", sa.BigInteger()),
        sa.Column("telegram_username", sa.String(64)),
        sa.Column("telegram_display_name", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "purpose IN ('login', 'grant', 'totp_setup', 'telegram_setup', 'telegram_reauth', 'reauth_attempt')",
            name=op.f("ck_mfa_challenges_purpose"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_mfa_challenges_attempts")),
    )
    for column in ("user_id", "session_id", "expires_at"):
        op.create_index(f"ix_mfa_challenges_{column}", "mfa_challenges", [column])
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])


def downgrade() -> None:
    enrolled = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM user_mfa WHERE totp_secret IS NOT NULL OR telegram_id IS NOT NULL)"
        )
    )
    if enrolled:
        raise RuntimeError("Disable enrolled MFA before downgrading authentication storage")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("mfa_challenges")
    op.drop_table("user_mfa")
    op.drop_column("users", "security_version")
