from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

FactorMethod = Literal["totp", "telegram"]
VerifyMethod = Literal["totp", "telegram", "recovery"]


class SecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EmptyRequest(SecretRequest):
    pass


class PasswordRequest(SecretRequest):
    password: str = Field(min_length=1, max_length=128, repr=False)


class ReauthRequest(PasswordRequest):
    method: VerifyMethod | None = None
    code: str | None = Field(default=None, min_length=1, max_length=64, repr=False)


class VerifyRequest(SecretRequest):
    method: VerifyMethod
    code: str = Field(min_length=1, max_length=64, repr=False)


class ConfirmRequest(SecretRequest):
    setup_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$", repr=False)


class TelegramAccount(BaseModel):
    id: str
    username: str | None
    display_name: str


class SecurityStatus(BaseModel):
    can_manage: bool
    mfa_enabled: bool
    methods: list[FactorMethod]
    available_methods: list[FactorMethod]
    telegram: TelegramAccount | None
    recovery_codes_remaining: int


class SecurityResult(BaseModel):
    security: SecurityStatus
    recovery_codes: list[str] | None = None


class MfaRequired(BaseModel):
    mfa_required: Literal[True] = True
    methods: list[VerifyMethod]
    csrf_token: str
    expires_at: datetime


class ExpiryResponse(BaseModel):
    expires_at: datetime


class SendResponse(BaseModel):
    sent: Literal[True] = True
    retry_after: int


class TotpSetupResponse(ExpiryResponse):
    setup_id: UUID
    secret: str
    otpauth_uri: str


class TelegramSetupResponse(ExpiryResponse):
    setup_id: UUID
    link: str


class TelegramSetupStatus(ExpiryResponse):
    status: Literal["waiting", "claimed"]
    account: TelegramAccount | None


class TelegramClaimRequest(SecretRequest):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    telegram_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    chat_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    username: str | None = Field(default=None, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)

    @field_validator("username", "display_name")
    @classmethod
    def no_nul(cls, value):
        if value is not None and "\x00" in value:
            raise ValueError("Invalid text")
        return value
