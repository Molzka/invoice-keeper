from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Invoice Keeper"
    app_timezone: str = "Europe/Moscow"
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str | None = Field(default=None, repr=False)
    admin_username: str | None = None
    admin_password: SecretStr | None = Field(default=None, repr=False)
    session_cookie_name: str = "session_id"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=604800, ge=60, le=2592000)
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    )
    login_rate_limit_attempts: int = Field(default=10, ge=1, le=1000)
    login_rate_limit_ip_attempts: int = Field(default=60, ge=1, le=10000)
    login_rate_limit_window_seconds: int = Field(default=900, ge=1, le=86400)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            url = make_url(value)
            valid = url.drivername == "postgresql+asyncpg" and bool(url.database)
        except Exception:
            valid = False
        if not valid:
            raise ValueError("DATABASE_URL must be a postgresql+asyncpg URL with a database")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        origins = []
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("ALLOWED_ORIGINS must contain explicit HTTP(S) origins")
            origins.append(value.rstrip("/"))
        if not origins:
            raise ValueError("ALLOWED_ORIGINS must not be empty")
        return origins

    @field_validator("session_cookie_name")
    @classmethod
    def validate_cookie_name(cls, value: str) -> str:
        if not value or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in value
        ):
            raise ValueError("SESSION_COOKIE_NAME must be a valid cookie name")
        return value

    @model_validator(mode="after")
    def validate_cookie_security(self) -> "Settings":
        if (
            self.session_cookie_name.startswith(("__Host-", "__Secure-"))
            and not self.session_cookie_secure
        ):
            raise ValueError("Prefixed cookies require SESSION_COOKIE_SECURE=true")
        if self.app_env == "production":
            if not self.session_cookie_secure:
                raise ValueError("Production requires SESSION_COOKIE_SECURE=true")
            if any(not origin.startswith("https://") for origin in self.allowed_origins):
                raise ValueError("Production requires HTTPS ALLOWED_ORIGINS")
        return self

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


settings = Settings()
