"""Integration fixtures use only an explicitly selected disposable PostgreSQL DB."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings
from app.db.session import Database
from app.main import create_app
from app.models import LoginRateLimit, User, UserSession

PASSWORD = "test-password-strong-123"
BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_database_url():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        raise pytest.UsageError(
            "PostgreSQL tests require TEST_DATABASE_URL ending in _test. "
            "Run: uv run --locked python scripts/test_postgres.py"
        )
    try:
        parsed_url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise pytest.UsageError("TEST_DATABASE_URL must be a valid PostgreSQL URL") from None
    if parsed_url.drivername != "postgresql+asyncpg" or not (
        parsed_url.database and parsed_url.database.endswith("_test")
    ):
        raise pytest.UsageError(
            "Tests require postgresql+asyncpg and an explicit database ending in _test."
        )

    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        diagnostics = result.stderr.replace(database_url, "<TEST_DATABASE_URL>")
        if parsed_url.password:
            diagnostics = diagnostics.replace(parsed_url.password, "<redacted>")
        pytest.fail(f"Could not migrate the disposable test database:\n{diagnostics}")
    return database_url


@pytest.fixture(scope="session")
def password_hash():
    return PasswordHash.recommended().hash(PASSWORD)


@pytest_asyncio.fixture
async def app(migrated_database_url):
    config = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated_database_url,
        allowed_origins=["http://testserver"],
        session_cookie_secure=False,
        session_ttl_seconds=3600,
        login_rate_limit_attempts=20,
        login_rate_limit_ip_attempts=100,
        login_rate_limit_window_seconds=60,
    )
    application = create_app(config)
    async with application.router.lifespan_context(application):
        async with application.state.database.session_factory() as session:
            # Only the explicitly selected *_test database is modified.
            for model in (UserSession, LoginRateLimit, User):
                await session.execute(delete(model))
            await session.commit()
        yield application


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as api_client:
        yield api_client


@pytest.fixture
def create_user(app, password_hash):
    async def create(
        username="admin",
        *,
        role="admin",
        is_active=True,
        display_name="Test User",
    ):
        async with app.state.database.session_factory() as session:
            user = User(
                username=username,
                display_name=display_name,
                password_hash=password_hash,
                role=role,
                is_active=is_active,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return create


@pytest.fixture
def login():
    async def authenticate(client, username="admin", password=PASSWORD):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return authenticate


@pytest_asyncio.fixture
async def delivery_db(migrated_database_url):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.delivery.schema import create_delivery_schema, drop_delivery_schema

    from .delivery_helpers import metadata

    database = Database(migrated_database_url)
    async with database.engine.begin() as connection:
        await connection.run_sync(
            lambda sync: create_delivery_schema(Operations(MigrationContext.configure(sync)))
        )
        await connection.run_sync(metadata.create_all)
    try:
        yield database
    finally:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.drop_all)
            await connection.run_sync(
                lambda sync: drop_delivery_schema(Operations(MigrationContext.configure(sync)))
            )
        await database.dispose()
