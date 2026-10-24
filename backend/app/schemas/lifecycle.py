from pydantic import BaseModel, ConfigDict

from app.schemas.payments import Amount, Currency, IsoDate, Title


class OneTimePaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: Title
    amount: Amount
    currency: Currency
    due_date: IsoDate
