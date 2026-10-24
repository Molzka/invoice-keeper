from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.users import Password, Username

RegistrationStatus = Literal["pending", "approved", "rejected"]


class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: Username
    password: Password = Field(repr=False)
    password_confirm: Password = Field(repr=False)
    message: str = Field(min_length=1, max_length=500)
    altcha: str = Field(min_length=1, max_length=8192, repr=False)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Недопустимый символ")
        if not value.strip():
            raise ValueError("Укажите имя или сообщение администратору")
        return value.strip()

    @model_validator(mode="after")
    def confirm_password(self) -> "RegistrationCreate":
        if self.password != self.password_confirm:
            raise ValueError("Пароли не совпадают")
        return self


class RegistrationAccepted(BaseModel):
    status: Literal["pending"] = "pending"
    message: str = (
        "Если для этого логина ещё нет аккаунта или активной заявки, заявка передана "
        "администратору. После одобрения войдите с выбранным логином и паролем."
    )


class RegistrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    message: str
    status: RegistrationStatus
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: UUID | None
    decision_note: str | None

    @field_validator("created_at", "reviewed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class RegistrationList(BaseModel):
    items: list[RegistrationRead]
    total: int
    limit: int
    offset: int


class RegistrationApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistrationReject(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    note: str | None = Field(default=None, max_length=300)

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("Недопустимый символ")
        return value
