"""Run checks in a temporary PostgreSQL database; never truncate the development DB."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402


async def main() -> int:
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL in backend/.env first.")
    url = make_url(settings.database_url)
    # Only this fresh, internally generated database is ever removed.
    database_name = f"invoice_keeper_{uuid4().hex}_test"
    connection = await asyncpg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        timeout=10,
    )
    created = False
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
        created = True
        env = os.environ.copy()
        env["DATABASE_URL"] = url.set(database=database_name).render_as_string(hide_password=False)
        env["TEST_DATABASE_URL"] = env["DATABASE_URL"]
        env["APP_ENV"] = "test"
        commands = [
            ["alembic", "upgrade", "head"],
            ["pytest", "-q", "-ra"],
            ["alembic", "check"],
            ["alembic", "downgrade", "base"],
            ["alembic", "upgrade", "head"],
            ["alembic", "check"],
        ]
        for command in commands:
            print("Running:", " ".join(command), flush=True)
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", *command],
                cwd=BACKEND,
                env=env,
                check=False,
            )
            if result.returncode:
                return result.returncode
        return 0
    finally:
        try:
            if created:
                await connection.execute(f'DROP DATABASE "{database_name}" WITH (FORCE)')
                print("Temporary test database removed.", flush=True)
        finally:
            await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
