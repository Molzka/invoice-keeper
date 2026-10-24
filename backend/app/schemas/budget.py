from datetime import date

from pydantic import BaseModel, Field

from app.schemas.payments import Currency


class BudgetCurrencyTotals(BaseModel):
    planned: str = Field(description="Оплаченные, неоплаченные периоды и прогноз вместе")
    paid: str = Field(description="Оплаченные существующие периоды по сроку оплаты")
    unpaid: str = Field(description="Неоплаченные существующие периоды")
    overdue: str = Field(description="Просроченная часть unpaid на дату расчёта")
    forecast: str = Field(description="Будущие сроки активных правил без созданного периода")


class BudgetMonth(BaseModel):
    month: int = Field(ge=1, le=12)
    totals: dict[Currency, BudgetCurrencyTotals]


class PaymentsBudget(BaseModel):
    year: int = Field(ge=1, le=9999)
    month: int | None = Field(ge=1, le=12)
    date_from: date
    date_to: date
    as_of_date: date
    timezone: str
    totals: dict[Currency, BudgetCurrencyTotals]
    months: list[BudgetMonth]
