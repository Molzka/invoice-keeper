from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

AuditAction = Literal[
    "payment.amount_changed",
    "payment.terms_changed",
    "payment.deleted",
    "payment.period_deleted",
    "payment.created",
    "payment.stopped",
    "payment.paid",
    "payment.unpaid",
    "payment.date_changed",
    "user.created",
    "user.updated",
    "user.deleted",
    "password.changed",
    "payment.receipt_updated",
    "payment.receipt_deleted",
]
AuditEntityType = Literal["payment", "user", "account"]
AUDIT_ACTION_LABELS: dict[str, str] = {
    "payment.amount_changed": "Изменена сумма периода",
    "payment.terms_changed": "Изменены условия платежа",
    "payment.deleted": "Удалён платёж",
    "payment.period_deleted": "Удалён период платежа",
    "payment.created": "Создан платёж",
    "payment.stopped": "Платёж прекращён",
    "payment.paid": "Отмечена оплата",
    "payment.unpaid": "Отменена оплата",
    "payment.date_changed": "Исправлена дата оплаты",
    "user.created": "Создан пользователь",
    "user.updated": "Изменён пользователь",
    "user.deleted": "Удалён пользователь",
    "password.changed": "Изменён пароль",
    "payment.receipt_updated": "Добавлено подтверждение оплаты",
    "payment.receipt_deleted": "Удалено подтверждение оплаты",
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
        "receipt",
        "amount_effective_from",
        "is_cancelled",
        "is_archived",
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
