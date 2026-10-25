from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.mfa import SecretRequest, TelegramAccount, TelegramClaimRequest
from app.schemas.payments import PaymentOccurrenceRead


class TelegramPaymentStatus(SecretRequest):
    available: bool
    can_manage: bool
    account: TelegramAccount | None


class ConfirmPaymentLink(SecretRequest):
    setup_id: UUID
    telegram_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class ClaimPaymentLink(TelegramClaimRequest):
    chat_id: int = Field(ge=-(2**63) + 1, le=2**63 - 1, strict=True)


class TelegramIdentity(SecretRequest):
    telegram_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    chat_id: int = Field(ge=-(2**63) + 1, le=2**63 - 1, strict=True)

    @field_validator("chat_id")
    @classmethod
    def nonzero_chat(cls, value):
        if value == 0:
            raise ValueError("Invalid chat")
        return value


class PrepareTelegramPayment(TelegramIdentity):
    occurrence_id: UUID


class ConfirmTelegramPayment(TelegramIdentity):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)


class PreparedTelegramPayment(SecretRequest):
    token: str
    payment: PaymentOccurrenceRead
    paid_on: date
    timezone: str
    expires_at: datetime


class TelegramPaymentResult(SecretRequest):
    outcome: Literal["paid", "already_paid", "already_processed"]
    payment: PaymentOccurrenceRead


class TelegramAccepted(SecretRequest):
    accepted: Literal[True] = True
