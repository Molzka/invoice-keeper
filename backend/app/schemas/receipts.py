import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator
from pydantic_core import PydanticCustomError


class ReceiptLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        # Do not let a URL parser silently strip a leading control character.
        if re.search(r"[\x00-\x20\x7f]", value) or "\\" in value:
            raise PydanticCustomError("receipt_url", "Укажите корректную HTTPS-ссылку")
        try:
            original = urlsplit(value)
            parsed = HttpUrl(value)
            valid = (
                parsed.scheme == "https"
                and bool(original.netloc)
                and bool(original.hostname)
                and bool(parsed.host)
                and parsed.username is None
                and parsed.password is None
                and parsed.port != 0
            )
        except (ValueError, ValidationError):
            valid = False
        if not valid:
            raise PydanticCustomError("receipt_url", "Укажите корректную HTTPS-ссылку")
        return value


class PaymentReceiptRead(BaseModel):
    id: UUID
    kind: Literal["file", "link"]
    url: str | None
    filename: str | None
    content_type: str | None
    size_bytes: int | None
    uploaded_at: datetime

    @field_validator("uploaded_at")
    @classmethod
    def timestamp_in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)
