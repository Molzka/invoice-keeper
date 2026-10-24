"""Align ordinary users with the frontend contract without losing existing accounts.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.execute("UPDATE users SET role = 'user' WHERE role = 'member'")
    op.alter_column("users", "role", existing_type=sa.String(16), server_default="user")
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('admin', 'user')")
    op.alter_column("users", "display_name", existing_type=sa.String(100), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE users SET display_name = username WHERE display_name IS NULL")
    op.alter_column("users", "display_name", existing_type=sa.String(100), nullable=False)
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.execute("UPDATE users SET role = 'member' WHERE role = 'user'")
    op.alter_column("users", "role", existing_type=sa.String(16), server_default="member")
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('admin', 'member')")
