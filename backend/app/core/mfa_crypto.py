import base64
import hashlib
import hmac
import secrets
from datetime import datetime

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.services.errors import api_error


def fernet(settings: Settings) -> Fernet:
    if not settings.mfa_encryption_key:
        raise api_error(503, "MFA_UNAVAILABLE", "Защита входа временно недоступна")
    return Fernet(settings.mfa_encryption_key.get_secret_value())


def encrypt_secret(settings: Settings, value: str) -> str:
    return fernet(settings).encrypt(value.encode("ascii")).decode("ascii")


def decrypt_secret(settings: Settings, value: str) -> str:
    try:
        return fernet(settings).decrypt(value.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError):
        raise api_error(503, "MFA_UNAVAILABLE", "Защита входа временно недоступна") from None


def code_digest(settings: Settings, challenge_id, code: str) -> str:
    fernet(settings)
    key = base64.urlsafe_b64decode(settings.mfa_encryption_key.get_secret_value())
    return hmac.new(key, f"mfa-code:{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def fresh_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def matching_totp_step(secret: str, code: str, now: datetime, last_step: int) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdecimal():
        return None
    current = int(now.timestamp()) // 30
    totp = pyotp.TOTP(secret)
    for step in (current, current - 1, current + 1):
        if step > last_step and hmac.compare_digest(totp.at(step * 30), code):
            return step
    return None


def recovery_digest(value: str) -> str:
    normalized = value.replace("-", "").replace(" ", "").upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fresh_recovery_codes() -> list[str]:
    result = []
    for _ in range(10):
        value = secrets.token_hex(16).upper()
        result.append("-".join(value[i : i + 8] for i in range(0, 32, 8)))
    return result
