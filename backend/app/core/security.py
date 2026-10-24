import hashlib
import hmac
import re
import secrets
from functools import lru_cache

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from starlette.concurrency import run_in_threadpool

_password_hash = PasswordHash.recommended()
_SESSION_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


async def hash_password(password: str) -> str:
    """Run Argon2 outside the event loop."""
    return await run_in_threadpool(_password_hash.hash, password)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    # Called only from the worker thread, including on the first unknown login.
    return _password_hash.hash(secrets.token_urlsafe(32))


def _verify_password(password: str, hashed_password: str | None) -> bool:
    try:
        valid = _password_hash.verify(password, hashed_password or _dummy_password_hash())
    except (UnknownHashError, ValueError):
        _password_hash.verify(password, _dummy_password_hash())
        return False
    return hashed_password is not None and valid


async def verify_password(password: str, hashed_password: str | None) -> bool:
    """Unknown users still perform an Argon2 verification."""
    return await run_in_threadpool(_verify_password, password, hashed_password)


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def valid_session_token(token: str | None) -> bool:
    return token is not None and _SESSION_TOKEN_PATTERN.fullmatch(token) is not None


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for_session(token: str) -> str:
    return hmac.new(token.encode("utf-8"), b"invoice-keeper-csrf", hashlib.sha256).hexdigest()


def verify_csrf_token(token: str, supplied: str | None) -> bool:
    if supplied is None:
        return False
    return hmac.compare_digest(
        csrf_token_for_session(token).encode("ascii"), supplied.encode("utf-8")
    )
