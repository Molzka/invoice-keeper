from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

AuditAction = Literal[
    "account.telegram_linked",
    "account.telegram_unlinked",
    "account.login",
    "account.login_failed",
    "account.logout",
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
    "registration.approved",
    "registration.rejected",
    "account.mfa_enabled",
    "account.mfa_disabled",
    "account.mfa_changed",
    "account.recovery_regenerated",
]
AuditEntityType = Literal["payment", "user", "account", "registration"]
AUDIT_ACTION_LABELS: dict[str, str] = {
    "account.telegram_linked": "Подключена оплата в Telegram",
    "account.telegram_unlinked": "Отключена оплата в Telegram",
    "account.login": "Вход в систему",
    "account.login_failed": "Неудачная попытка входа",
    "account.logout": "Выход из системы",
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
    "registration.approved": "Одобрена заявка сотрудника",
    "registration.rejected": "Отклонена заявка сотрудника",
    "account.mfa_enabled": "Подключена дополнительная защита входа",
    "account.mfa_disabled": "Отключена дополнительная защита входа",
    "account.mfa_changed": "Изменён способ подтверждения входа",
    "account.recovery_regenerated": "Обновлены резервные коды",
}
SAFE_CHANGE_FIELDS = frozenset(
    {
        "title",
        "periodicity",
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
    id: UUID | None
    username: str


class AuditEntity(BaseModel):
    type: AuditEntityType
    id: UUID | None
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
