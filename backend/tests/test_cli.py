from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.cli import cleanup_auth, create_admin
from app.models import LoginRateLimit, User, UserSession
from app.schemas.users import UserCreate

from .conftest import PASSWORD

pytestmark = pytest.mark.asyncio


async def test_bootstrap_admin_can_log_in_and_duplicate_cannot_reset_account(app, client, login):
    data = UserCreate(username=" ADMIN ", password=PASSWORD)
    await create_admin(app.state.database, data)
    authentication = await login(client)
    assert authentication["user"]["username"] == "admin"
    assert authentication["user"]["role"] == "admin"
    async with app.state.database.session_factory() as session:
        original = await session.scalar(select(User).where(User.username == "admin"))
        original_hash = original.password_hash
    with pytest.raises(ValueError, match="уже существует"):
        await create_admin(
            app.state.database,
            UserCreate(
                username="admin",
                password="different-password-456",
            ),
        )
    async with app.state.database.session_factory() as session:
        unchanged = await session.scalar(select(User).where(User.username == "admin"))
        assert unchanged.password_hash == original_hash
        assert unchanged.display_name is None
        assert unchanged.role == "admin"
        assert unchanged.is_active
    await login(client)


async def test_cleanup_removes_expired_records_and_keeps_active_ones(app, create_user):
    user = await create_user()
    now = datetime.now(UTC)
    async with app.state.database.session_factory() as session:
        session.add_all(
            [
                UserSession(
                    user_id=user.id, token_hash="a" * 64, expires_at=now - timedelta(days=1)
                ),
                UserSession(
                    user_id=user.id, token_hash="b" * 64, expires_at=now + timedelta(days=1)
                ),
                LoginRateLimit(key="c" * 64, attempts=1, window_started_at=now - timedelta(days=2)),
                LoginRateLimit(
                    key="d" * 64, attempts=1, window_started_at=now + timedelta(seconds=1)
                ),
            ]
        )
        await session.commit()
    assert await cleanup_auth(app.state.database) == (1, 1)
    async with app.state.database.session_factory() as session:
        assert (await session.scalars(select(UserSession.token_hash))).all() == ["b" * 64]
        assert (await session.scalars(select(LoginRateLimit.key))).all() == ["d" * 64]
