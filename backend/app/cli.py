"""Local administration: uv run python -m app.cli --help."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Database
from app.models import LoginRateLimit, User, UserSession
from app.models.mfa import MfaChallenge
from app.models.registration import RegistrationChallenge
from app.schemas.users import UserCreate
from app.services.users import ADMIN_LOCK_KEY


async def create_admin(database: Database, data: UserCreate) -> None:
    password_hash = await hash_password(data.password)
    async with database.session_factory() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK_KEY})
        if await session.scalar(select(User.id).where(User.username == data.username)):
            raise ValueError("Пользователь с таким логином уже существует. Его пароль не изменён.")
        session.add(
            User(
                username=data.username,
                password_hash=password_hash,
                role="admin",
                is_active=True,
            )
        )
        await session.commit()


async def cleanup_auth(database: Database) -> tuple[int, int]:
    now = datetime.now(UTC)
    async with database.session_factory() as session:
        await session.execute(delete(MfaChallenge).where(MfaChallenge.expires_at <= now))
        await session.execute(
            delete(RegistrationChallenge).where(RegistrationChallenge.expires_at <= now)
        )
        expired = await session.execute(delete(UserSession).where(UserSession.expires_at <= now))
        limits = await session.execute(
            delete(LoginRateLimit).where(
                LoginRateLimit.window_started_at
                < now
                - timedelta(
                    seconds=max(
                        settings.login_rate_limit_window_seconds,
                        settings.password_change_rate_limit_window_seconds,
                        settings.mfa_rate_window_seconds,
                    )
                ),
            )
        )
        await session.commit()
        return expired.rowcount, limits.rowcount


async def run(args: argparse.Namespace, data: UserCreate | None) -> None:
    if not settings.database_url:
        raise ValueError("Укажите DATABASE_URL в backend/.env.")
    database = Database(settings.database_url)
    try:
        if args.command == "create-admin":
            assert data is not None
            await create_admin(database, data)
            print(f"Администратор {data.username} создан.")
        else:
            sessions, limits = await cleanup_auth(database)
            print(f"Удалено истёкших сессий: {sessions}; старых счётчиков входа: {limits}.")
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальное управление Invoice Keeper")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create-admin", help="Создать администратора, не изменяя существующих"
    )
    create.add_argument(
        "--username",
        help="Ручной ввод пароля; без аргумента используются ADMIN_USERNAME/ADMIN_PASSWORD",
    )
    commands.add_parser("cleanup-auth", help="Удалить истёкшие сессии и устаревшие счётчики входа")
    args = parser.parse_args()
    data = None
    try:
        if args.command == "create-admin":
            if args.username is None:
                username = settings.admin_username
                password = (
                    settings.admin_password.get_secret_value() if settings.admin_password else None
                )
                if not username or not password:
                    raise ValueError("Укажите ADMIN_USERNAME и ADMIN_PASSWORD в backend/.env.")
            else:
                username = args.username
                password = getpass("Пароль (8–128 символов): ")
                if password != getpass("Повторите пароль: "):
                    raise ValueError("Пароли не совпадают.")
            data = UserCreate(
                username=username,
                password=password,
            )
        asyncio.run(run(args, data))
    except ValidationError:
        parser.exit(1, "Некорректные данные: логин 3–64 символа a-z/0-9/_.-, пароль 8–128.\n")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except IntegrityError:
        parser.exit(1, "Пользователь с таким логином уже существует.\n")
    except (SQLAlchemyError, OSError):
        parser.exit(
            1, "Не удалось выполнить команду. Проверьте PostgreSQL, DATABASE_URL и миграции.\n"
        )
    except (KeyboardInterrupt, EOFError):
        parser.exit(1, "Команда отменена.\n")


if __name__ == "__main__":
    main()
