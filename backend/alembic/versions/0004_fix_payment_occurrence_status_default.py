"""Fix the default payment occurrence status.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "payment_occurrences",
        "status",
        existing_type=sa.String(length=16),
        server_default=sa.text("'unpaid'"),
    )


def downgrade() -> None:
    op.alter_column(
        "payment_occurrences",
        "status",
        existing_type=sa.String(length=16),
        server_default="'unpaid'",
    )
