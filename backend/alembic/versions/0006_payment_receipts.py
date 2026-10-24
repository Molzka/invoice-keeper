"""Store one private file or proof link per payment occurrence.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("url", sa.String(2048)),
        sa.Column("filename", sa.String(180)),
        sa.Column("content_type", sa.String(32)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("data", sa.LargeBinary()),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('file', 'link')", name=op.f("ck_payment_receipts_kind")),
        sa.CheckConstraint(
            "(kind = 'link' AND url IS NOT NULL AND filename IS NULL AND content_type IS NULL "
            "AND size_bytes IS NULL AND data IS NULL) OR "
            "(kind = 'file' AND url IS NULL AND filename IS NOT NULL AND "
            "content_type IS NOT NULL AND content_type IN ('application/pdf', 'image/png', 'image/jpeg') AND "
            "size_bytes IS NOT NULL AND size_bytes BETWEEN 1 AND 5242880 AND data IS NOT NULL "
            "AND octet_length(data) = size_bytes)",
            name=op.f("ck_payment_receipts_content"),
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["payment_occurrences.id"],
            ondelete="CASCADE",
            name=op.f("fk_payment_receipts_occurrence_id_payment_occurrences"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_receipts")),
        sa.UniqueConstraint("occurrence_id", name=op.f("uq_payment_receipts_occurrence_id")),
    )


def downgrade() -> None:
    op.drop_table("payment_receipts")
