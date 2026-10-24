import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from .conftest import BACKEND_DIR


@pytest.mark.asyncio
async def test_upgrade_preserves_existing_accounts_passwords_and_sessions(migrated_database_url):
    env = os.environ.copy()
    env["DATABASE_URL"] = migrated_database_url

    def migrate(target, direction="upgrade"):
        subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True,
        )

    connection = await asyncpg.connect(
        make_url(migrated_database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    user_id, admin_id, session_id, new_id = (uuid4() for _ in range(4))
    suffix = uuid4().hex[:12]
    try:
        migrate("0001", "downgrade")
        await connection.execute(
            """
            INSERT INTO users(id, username, display_name, password_hash, role)
            VALUES ($1, $2, 'Legacy user', 'preserved-hash', 'member'),
                   ($3, $4, 'Legacy admin', 'admin-hash', 'admin')
        """,
            user_id,
            "legacy_" + suffix,
            admin_id,
            "legacy_admin_" + suffix,
        )
        await connection.execute(
            """
            INSERT INTO user_sessions(id, user_id, token_hash, expires_at)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP + INTERVAL '1 day')
        """,
            session_id,
            user_id,
            uuid4().hex + uuid4().hex,
        )
        migrate("head")
        user = await connection.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        assert user["role"] == "user" and user["password_hash"] == "preserved-hash"
        assert user["display_name"] == "Legacy user"
        assert await connection.fetchval("SELECT role FROM users WHERE id=$1", admin_id) == "admin"
        assert (
            await connection.fetchval("SELECT user_id FROM user_sessions WHERE id=$1", session_id)
            == user_id
        )
        await connection.execute(
            "INSERT INTO users(id, username, password_hash) VALUES ($1, $2, 'new-hash')",
            new_id,
            "new_" + suffix,
        )
        assert await connection.fetchval("SELECT role FROM users WHERE id=$1", new_id) == "user"
        migrate("0001", "downgrade")
        assert await connection.fetchval("SELECT role FROM users WHERE id=$1", user_id) == "member"
        assert (
            await connection.fetchval("SELECT display_name FROM users WHERE id=$1", new_id)
            == "new_" + suffix
        )
    finally:
        await connection.close()
        migrate("head")


@pytest.mark.asyncio
async def test_amount_snapshot_upgrade_backfills_existing_paid_and_unpaid_history(
    migrated_database_url,
):
    env = os.environ.copy()
    env["DATABASE_URL"] = migrated_database_url

    def migrate(target, direction="upgrade"):
        subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True,
        )

    connection = await asyncpg.connect(
        make_url(migrated_database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    payment_id, paid_id, unpaid_id = (uuid4() for _ in range(3))
    try:
        migrate("0004", "downgrade")
        await connection.execute(
            """
            INSERT INTO recurring_payments
                (id, title, amount, currency, first_due_date, periodicity, anchor_day)
            VALUES ($1, 'Legacy amount snapshot', 12345.67, 'USD', '2026-01-31', 'monthly', 31)
            """,
            payment_id,
        )
        await connection.execute(
            """
            INSERT INTO payment_occurrences
                (id, recurring_payment_id, due_date, status, paid_on)
            VALUES ($1, $2, '2026-01-31', 'paid', '2026-02-02'),
                   ($3, $2, '2026-02-28', 'unpaid', NULL)
            """,
            paid_id,
            payment_id,
            unpaid_id,
        )
        for cycle in range(2):
            migrate("head")
            rows = await connection.fetch(
                """SELECT id, due_date, status, paid_on, amount, currency, amount_is_custom
                   FROM payment_occurrences WHERE recurring_payment_id=$1 ORDER BY due_date""",
                payment_id,
            )
            assert len(rows) == 2
            assert [
                (row["id"], row["due_date"], row["status"], row["paid_on"]) for row in rows
            ] == [
                (paid_id, date(2026, 1, 31), "paid", date(2026, 2, 2)),
                (unpaid_id, date(2026, 2, 28), "unpaid", None),
            ]
            assert all(row["amount"] == Decimal("12345.67") for row in rows)
            assert all(
                row["currency"] == "USD" and row["amount_is_custom"] is False for row in rows
            )
            assert (
                await connection.fetchval(
                    "SELECT amount_effective_from FROM recurring_payments WHERE id=$1", payment_id
                )
                is None
            )
            if cycle == 0:
                migrate("0004", "downgrade")
                assert (
                    await connection.fetchval(
                        """SELECT COUNT(*) FROM information_schema.columns
                       WHERE table_name='payment_occurrences' AND column_name='amount'"""
                    )
                    == 0
                )
                assert (
                    await connection.fetchval(
                        "SELECT COUNT(*) FROM payment_occurrences WHERE recurring_payment_id=$1",
                        payment_id,
                    )
                    == 2
                )
    finally:
        await connection.execute(
            "DELETE FROM payment_occurrences WHERE recurring_payment_id=$1", payment_id
        )
        await connection.execute("DELETE FROM recurring_payments WHERE id=$1", payment_id)
        await connection.close()
        migrate("head")
