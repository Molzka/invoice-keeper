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
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
UserRole = Literal["admin", "member"]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: Username
    password: Password = Field(repr=False)
    display_name: DisplayName
    role: UserRole = "member"
    is_active: bool = True


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    display_name: DisplayName | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: Password | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def reject_null_updates(self) -> "UserUpdate":
        if not self.model_fields_set:
            raise ValueError("Укажите хотя бы одно поле для изменения")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Поля пользователя не могут быть null")
        return self


class UserList(BaseModel):
    items: list[UserRead]
    total: int
    limit: int
    offset: int
