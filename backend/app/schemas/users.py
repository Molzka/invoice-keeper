from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


def normalize_username(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


Username = Annotated[
    str,
    StringConstraints(min_length=3, max_length=64, pattern=r"^[a-z0-9_.-]+$"),
    BeforeValidator(normalize_username),
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
UserRole = Literal["admin", "user"]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: UserRole
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamps_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: Username
    password: Password = Field(repr=False)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: Username | None = None
    password: Password | None = Field(default=None, repr=False)

    @field_validator("username", "password", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Поле не может быть null")
        return value

    @model_validator(mode="after")
    def reject_null_updates(self) -> "UserUpdate":
        if not self.model_fields_set:
            raise ValueError("Укажите хотя бы одно поле для изменения")
        return self


class UserList(BaseModel):
    items: list[UserRead]
    total: int
    limit: int
    offset: int
