from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

AuditAction = Literal[
    "payment.created",
    "payment.stopped",
    "payment.paid",
    "payment.unpaid",
    "payment.date_changed",
    "user.created",
    "user.updated",
    "user.deleted",
    "password.changed",
]
AuditEntityType = Literal["payment", "user", "account"]
AUDIT_ACTION_LABELS: dict[str, str] = {
    "payment.created": "Создан платёж",
    "payment.stopped": "Платёж прекращён",
    "payment.paid": "Отмечена оплата",
    "payment.unpaid": "Отменена оплата",
    "payment.date_changed": "Исправлена дата оплаты",
    "user.created": "Создан пользователь",
    "user.updated": "Изменён пользователь",
    "user.deleted": "Удалён пользователь",
    "password.changed": "Изменён пароль",
}
SAFE_CHANGE_FIELDS = frozenset(
    {
        "title",
        "amount",
        "currency",
        "first_due_date",
        "status",
        "paid_on",
        "due_date",
        "is_active",
        "username",
    }
)


class AuditActor(BaseModel):
    id: UUID
    username: str


class AuditEntity(BaseModel):
    type: AuditEntityType
    id: UUID
    title: str


class AuditChange(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    field: str
    label: str
    before: str | None
    after: str | None


class AuditEventRead(BaseModel):
    id: UUID
    occurred_at: datetime
    actor: AuditActor
    action: AuditAction
    entity: AuditEntity
    changes: list[AuditChange]

    @field_validator("occurred_at")
    @classmethod
    def timestamp_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class AuditEventList(BaseModel):
    items: list[AuditEventRead]
    total: int
    limit: int
    offset: int
