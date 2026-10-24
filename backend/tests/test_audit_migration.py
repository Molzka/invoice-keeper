import os
import subprocess
import sys
from datetime import date
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from .conftest import BACKEND_DIR


@pytest.mark.asyncio
async def test_audit_upgrade_and_downgrade_preserve_existing_business_data(migrated_database_url):
    environment = os.environ.copy()
    environment["DATABASE_URL"] = migrated_database_url

    def migrate(target, direction="upgrade"):
        subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=BACKEND_DIR,
            env=environment,
            check=True,
            capture_output=True,
        )

    connection = await asyncpg.connect(
        make_url(migrated_database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    user_id, session_id, payment_id, period_id, delivery_id = (uuid4() for _ in range(5))
    tables = {
        "users": user_id,
        "user_sessions": session_id,
        "recurring_payments": payment_id,
        "payment_occurrences": period_id,
        "reminder_deliveries": delivery_id,
    }
    try:
        migrate("0004", "downgrade")
        await connection.execute(
            "INSERT INTO users(id, username, password_hash, role) VALUES ($1, $2, 'preserved-hash', 'user')",
            user_id,
            "audit_legacy_" + uuid4().hex[:12],
        )
        await connection.execute(
            "INSERT INTO user_sessions(id, user_id, token_hash, expires_at) "
            "VALUES ($1, $2, $3, CURRENT_TIMESTAMP + INTERVAL '1 day')",
            session_id,
            user_id,
            uuid4().hex + uuid4().hex,
        )
        await connection.execute(
            "INSERT INTO recurring_payments(id, title, amount, currency, first_due_date, periodicity, anchor_day) "
            "VALUES ($1, 'Preserved payment', 10.50, 'EUR', $2, 'monthly', 30)",
            payment_id,
            date(2026, 11, 30),
        )
        await connection.execute(
            "INSERT INTO payment_occurrences(id, recurring_payment_id, due_date) VALUES ($1, $2, $3)",
            period_id,
            payment_id,
            date(2026, 11, 30),
        )
        await connection.execute(
            "INSERT INTO reminder_deliveries(id, payment_id, occurrence_id, scheduled_at, available_at) "
            "VALUES ($1, $2, $3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            delivery_id,
            payment_id,
            period_id,
        )
        original = {
            table: await connection.fetchrow(f"SELECT * FROM {table} WHERE id=$1", record_id)
            for table, record_id in tables.items()
        }
        migrate("0005")
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == "0005"
        assert await connection.fetchval("SELECT COUNT(*) FROM audit_events") == 0
        for table, record_id in tables.items():
            assert (
                await connection.fetchrow(f"SELECT * FROM {table} WHERE id=$1", record_id)
                == original[table]
            )
        await connection.execute(
            "INSERT INTO audit_events(id, actor_id, actor_username, action, entity_type, entity_id, entity_title) "
            "VALUES ($1, $2, 'Historical actor', 'payment.created', 'payment', $3, 'Historical payment')",
            uuid4(),
            uuid4(),
            payment_id,
        )
        migrate("0004", "downgrade")
        assert await connection.fetchval("SELECT to_regclass('audit_events')") is None
        for table, record_id in tables.items():
            assert (
                await connection.fetchrow(f"SELECT * FROM {table} WHERE id=$1", record_id)
                == original[table]
            )
    finally:
        for table, record_id in reversed(list(tables.items())):
            await connection.execute(f"DELETE FROM {table} WHERE id=$1", record_id)
        await connection.close()
        migrate("head")
