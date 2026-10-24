"""Run checks in a temporary PostgreSQL database; never truncate the development DB."""

import asyncio
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import asyncpg
from pwdlib import PasswordHash
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402


async def check_admin_bootstrap(env: dict[str, str]) -> None:
    """Exercise the real CLI with a private .env and the disposable database."""
    password = secrets.token_urlsafe(32)
    replacement = secrets.token_urlsafe(32)
    probe_env = {
        key: value
        for key, value in env.items()
        if key.upper() not in {"ADMIN_USERNAME", "ADMIN_PASSWORD"}
    }
    url = make_url(env["DATABASE_URL"]).set(drivername="postgresql")
    connection = await asyncpg.connect(url.render_as_string(hide_password=False), timeout=10)
    try:
        with tempfile.TemporaryDirectory(prefix="invoice-keeper-admin-") as directory:
            probe = Path(directory)
            shutil.copytree(
                BACKEND / "app", probe / "app", ignore=shutil.ignore_patterns("__pycache__")
            )
            original = None
            for supplied, expected_status in [(password, 0), (replacement, 1), ("", 1)]:
                (probe / ".env").write_text(
                    f"ADMIN_USERNAME=bootstrap_check\nADMIN_PASSWORD='{supplied}'\n",
                    encoding="utf-8",
                )
                result = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-X", "utf8", "-m", "app.cli", "create-admin"],
                    cwd=probe,
                    env=probe_env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                    check=False,
                )
                if result.returncode != expected_status:
                    raise RuntimeError("Administrator CLI returned an unexpected exit status")
                if any(
                    secret in result.stdout + result.stderr for secret in (password, replacement)
                ):
                    raise RuntimeError("Administrator CLI exposed a password")
                row = await connection.fetchrow(
                    "SELECT id, role, password_hash FROM users WHERE username = $1",
                    "bootstrap_check",
                )
                if original is None:
                    if row is None or row["role"] != "admin":
                        raise RuntimeError("Administrator was not created from .env")
                    if not PasswordHash.recommended().verify(password, row["password_hash"]):
                        raise RuntimeError("Administrator password does not match .env")
                    original = row
                elif row != original:
                    raise RuntimeError("Repeated bootstrap changed the existing administrator")
        print(
            "Administrator .env bootstrap, duplicate and missing-password checks passed.",
            flush=True,
        )
    finally:
        await connection.close()


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
            if command == ["alembic", "upgrade", "head"]:
                await check_admin_bootstrap(env)
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
