import os
import subprocess
import sys
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
