import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_requires_secure_cookie_and_explicit_https_origins():
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(_env_file=None, app_env="production", session_cookie_secure=False)
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            _env_file=None,
            app_env="production",
            session_cookie_secure=True,
            allowed_origins=["http://example.com"],
        )
    config = Settings(
        _env_file=None,
        app_env="production",
        session_cookie_secure=True,
        allowed_origins=["https://example.com"],
    )
    assert config.session_cookie_secure


def test_invalid_database_url_does_not_expose_password_in_error():
    secret = "fake-database-password-for-test"
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, database_url=f"mysql://user:{secret}@localhost/example")
    assert secret not in str(caught.value)
    assert "input_value" not in str(caught.value)


@pytest.mark.parametrize(
    "origin", ["*", "https://user:password@example.com", "https://example.com/path"]
)
def test_invalid_cors_origins_are_rejected(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allowed_origins=[origin])


def test_host_cookie_prefix_requires_secure_flag():
    with pytest.raises(ValidationError, match="Prefixed cookies"):
        Settings(_env_file=None, session_cookie_name="__Host-session", session_cookie_secure=False)
