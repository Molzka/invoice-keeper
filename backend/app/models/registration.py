from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status"),
        CheckConstraint(
            "(status = 'pending' AND password_hash IS NOT NULL AND reviewed_at IS NULL) OR "
            "(status <> 'pending' AND password_hash IS NULL AND reviewed_at IS NOT NULL)",
            name="review_state",
        ),
        Index(
            "uq_registration_requests_pending_username",
            "username",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
        Index("ix_registration_requests_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class RegistrationChallenge(Base):
    __tablename__ = "registration_challenges"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    challenge: Mapped[dict] = mapped_column(JSONB)
    # This ephemeral key authenticates one public proof-of-work challenge only.
    # Plain DeclarativeBase does not support dataclass repr= column options.
    verification_key: Mapped[str] = mapped_column(Text)
    ip_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    def __repr__(self) -> str:
        return "<RegistrationChallenge [private]>"
