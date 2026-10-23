from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class LoginRateLimit(Base):
    __tablename__ = "login_rate_limits"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
