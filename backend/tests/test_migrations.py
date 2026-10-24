import os
import re
import runpy
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
async def test_upgrade_preserves_existing_accounts_passwords_and_sessions(
    app, migrated_database_url
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
    app,
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


def test_payment_migrations_extend_released_security_chain_without_duplicate_heads():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    configuration = Config(str(BACKEND_DIR / "alembic.ini"))
    migrations = ScriptDirectory.from_config(configuration)
    assert len(migrations.get_heads()) == 1
    assert migrations.get_revision("0007").module.__file__.endswith("0007_mfa.py")
    assert migrations.get_revision("0008").module.__file__.endswith("0008_registration_requests.py")
    assert migrations.get_revision("0009").down_revision == "0008"
    assert migrations.get_revision("0010").down_revision == "0009"
    assert {revision.revision for revision in migrations.walk_revisions()} >= {
        "0007",
        "0008",
        "0009",
        "0010",
    }


def test_lifecycle_audit_migration_preserves_registration_and_security_actions():
    from typing import get_args

    from app.models import AuditEvent
    from app.schemas.audit import AuditAction

    versions = BACKEND_DIR / "alembic" / "versions"
    security = runpy.run_path(str(versions / "0008_registration_requests.py"))
    lifecycle = runpy.run_path(str(versions / "0010_payment_lifecycle.py"))

    def actions(value):
        return set(re.findall(r"'([^']+)'", value))

    previous = actions(security["OLD_ACTIONS"]) | actions(security["NEW_ACTIONS"])
    added = {
        "payment.amount_changed",
        "payment.terms_changed",
        "payment.deleted",
        "payment.period_deleted",
    }
    assert actions(lifecycle["OLD_ACTIONS"]) == previous
    assert actions(lifecycle["NEW_ACTIONS"]) == previous | added
    authentication = runpy.run_path(str(versions / "0011_auth_audit.py"))
    auth_actions = {"account.login", "account.login_failed", "account.logout"}
    assert actions(authentication["OLD_ACTIONS"]) == previous | added
    assert actions(authentication["AUTH_ACTIONS"]) == auth_actions
    assert set(get_args(AuditAction)) == previous | added | auth_actions
    constraint = next(
        item for item in AuditEvent.__table__.constraints if item.name == "ck_audit_events_action"
    )
    assert actions(str(constraint.sqltext)) == previous | added | auth_actions


@pytest.mark.asyncio
async def test_auth_audit_migration_preserves_old_events_and_refuses_lossy_downgrade(
    app, migrated_database_url
):
    env = {**os.environ, "DATABASE_URL": migrated_database_url}

    def migrate(direction, target):
        return subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            check=False,
        )

    connection = await asyncpg.connect(
        make_url(migrated_database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    old_id, new_id, user_id = uuid4(), uuid4(), uuid4()
    try:
        assert migrate("downgrade", "0010").returncode == 0
        await connection.execute(
            "INSERT INTO audit_events(id, actor_id, actor_username, action, entity_type, entity_id, entity_title) "
            "VALUES ($1, $2, 'original', 'user.created', 'user', $2, 'original')",
            old_id,
            user_id,
        )
        before = await connection.fetchrow("SELECT * FROM audit_events WHERE id=$1", old_id)
        assert migrate("upgrade", "head").returncode == 0
        assert await connection.fetchrow("SELECT * FROM audit_events WHERE id=$1", old_id) == before
        await connection.execute(
            "INSERT INTO audit_events(id, actor_username, action, entity_type, entity_title) "
            "VALUES ($1, 'missing', 'account.login_failed', 'account', 'missing')",
            new_id,
        )
        refused = migrate("downgrade", "0010")
        assert refused.returncode != 0
        assert b"authentication history exists" in refused.stderr
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0011"
        assert await connection.fetchval("SELECT count(*) FROM audit_events") == 2
    finally:
        await connection.execute("DELETE FROM audit_events WHERE id IN ($1, $2)", old_id, new_id)
        await connection.close()
        assert migrate("upgrade", "head").returncode == 0
