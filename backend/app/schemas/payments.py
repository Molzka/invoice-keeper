import re
from datetime import UTC, date, datetime
from decimal import Decimal
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
from pydantic_core import PydanticCustomError

Currency = Literal["RUB", "USD", "EUR"]
PaymentStatus = Literal["paid", "unpaid"]
MAX_PAYMENT_AMOUNT = Decimal("999999999999.99")
MIN_PAYMENT_AMOUNT = Decimal("0.01")


def validate_iso_date(value: object) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise PydanticCustomError("date_format", "Передайте дату в формате YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PydanticCustomError(
            "date_format", "Передайте существующую дату в формате YYYY-MM-DD"
        ) from None


IsoDate = Annotated[date, BeforeValidator(validate_iso_date)]


def validate_amount(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]{2}", value) is None:
        raise PydanticCustomError(
            "money_format",
            "Передайте сумму строкой с точкой и ровно двумя знаками после неё",
        )
    amount = Decimal(value)
    if not MIN_PAYMENT_AMOUNT <= amount <= MAX_PAYMENT_AMOUNT:
        raise PydanticCustomError(
            "money_range",
            "Сумма должна быть от 0.01 до 999999999999.99",
        )
    return value


Amount = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]+\.[0-9]{2}$"),
    BeforeValidator(validate_amount),
]
Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00]*$"),
]


class RecurringPaymentCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        json_schema_extra={
            "examples": [
                {
                    "title": "Аренда офиса",
                    "amount": "45000.00",
                    "currency": "RUB",
                    "first_due_date": "2026-10-31",
                    "periodicity": "monthly",
                },
                {
                    "title": "Cloud storage",
                    "amount": "25.00",
                    "currency": "USD",
                    "first_due_date": "2026-10-28",
                    "periodicity": "monthly",
                },
                {
                    "title": "Телефон",
                    "amount": "9.00",
                    "currency": "EUR",
                    "first_due_date": "2026-10-28",
                    "periodicity": "monthly",
                },
            ]
        },
    )

    title: Title
    amount: Amount = Field(description="Строка с точкой и ровно двумя десятичными знаками")
    currency: Currency
    first_due_date: IsoDate
    periodicity: Literal["monthly"]


class AmountCurrencyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        json_schema_extra={"examples": [{"amount": "45000.50", "currency": "RUB"}]},
    )

    amount: Amount = Field(description="Строка с точкой и ровно двумя десятичными знаками")
    currency: Currency


class PaymentStateUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        json_schema_extra={
            "examples": [
                {"status": "paid", "paid_on": "2026-10-31"},
                {"status": "paid", "paid_on": "2026-11-03"},
                {"status": "paid", "paid_on": "2026-10-30"},
                {"status": "unpaid", "paid_on": None},
            ]
        },
    )

    status: PaymentStatus
    paid_on: IsoDate | None

    @model_validator(mode="after")
    def validate_state(self) -> "PaymentStateUpdate":
        if (self.status == "paid") != (self.paid_on is not None):
            raise PydanticCustomError(
                "payment_state",
                "Для paid нужна дата paid_on, для unpaid требуется null",
            )
        return self


class RecurringPaymentRead(BaseModel):
    id: UUID
    title: str
    amount: str
    currency: Currency
    amount_effective_from: date | None = None
    first_due_date: date
    next_due_date: date | None
    periodicity: Literal["monthly", "once"]
    is_archived: bool = False
    anchor_day: int
    is_active: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamp_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class RecurringAmountUpdateResponse(BaseModel):
    payment: RecurringPaymentRead
    effective_from: date
    updated_periods: int
    preserved_custom_periods: int


class PaymentOccurrenceRead(BaseModel):
    id: UUID
    recurring_payment_id: UUID
    title: str
    amount: str
    currency: Currency
    due_date: date
    amount_is_custom: bool
    periodicity: Literal["monthly", "once"] = "monthly"
    is_cancelled: bool = False
    status: PaymentStatus
    paid_on: date | None
    is_overdue: bool
    paid_late: bool
    days_late: int
    recurring_payment_is_active: bool


class RecurringPaymentList(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": "f059226b-8948-4da4-b33e-3b22844b4587",
                            "title": "Аренда офиса",
                            "amount": "45000.00",
                            "currency": "RUB",
                            "amount_effective_from": None,
                            "first_due_date": "2026-10-31",
                            "next_due_date": "2026-10-31",
                            "periodicity": "monthly",
                            "anchor_day": 31,
                            "is_active": True,
                            "created_at": "2026-10-23T09:30:00Z",
                        }
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
                {"items": [], "total": 0, "limit": 50, "offset": 0},
            ]
        }
    )

    items: list[RecurringPaymentRead]
    total: int
    limit: int
    offset: int


class PaymentOccurrenceList(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": "349e2b3b-1683-490a-a0ac-608cefc30248",
                            "recurring_payment_id": "f059226b-8948-4da4-b33e-3b22844b4587",
                            "title": "Аренда офиса",
                            "amount": "45000.00",
                            "currency": "RUB",
                            "due_date": "2026-10-31",
                            "amount_is_custom": False,
                            "status": "unpaid",
                            "paid_on": None,
                            "is_overdue": False,
                            "paid_late": False,
                            "days_late": 0,
                            "recurring_payment_is_active": True,
                        }
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
                {"items": [], "total": 0, "limit": 50, "offset": 0},
            ]
        }
    )

    items: list[PaymentOccurrenceRead]
    total: int
    limit: int
    offset: int


class CurrencyTotals(BaseModel):
    planned: str
    paid: str
    unpaid: str
    overdue: str


class PaymentsSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date_from": "2026-10-01",
                    "date_to": "2026-10-31",
                    "as_of_date": "2026-10-23",
                    "timezone": "Europe/Moscow",
                    "totals": {
                        currency: {
                            "planned": "0.00",
                            "paid": "0.00",
                            "unpaid": "0.00",
                            "overdue": "0.00",
                        }
                        for currency in ("RUB", "USD", "EUR")
                    },
                }
            ]
        }
    )

    date_from: date
    date_to: date
    as_of_date: date
    timezone: str = Field(examples=["Europe/Moscow"])
    totals: dict[Currency, CurrencyTotals]
