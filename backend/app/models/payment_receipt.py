from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now

MAX_RECEIPT_BYTES = 5 * 1024 * 1024


class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"
    __table_args__ = (
        CheckConstraint("kind IN ('file', 'link')", name="kind"),
        CheckConstraint(
            "(kind = 'link' AND url IS NOT NULL AND filename IS NULL AND content_type IS NULL "
            "AND size_bytes IS NULL AND data IS NULL) OR "
            "(kind = 'file' AND url IS NULL AND filename IS NOT NULL AND "
            "content_type IS NOT NULL AND content_type IN ('application/pdf', 'image/png', 'image/jpeg') AND "
            "size_bytes IS NOT NULL AND size_bytes BETWEEN 1 AND 5242880 AND data IS NOT NULL "
            "AND octet_length(data) = size_bytes)",
            name="content",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    occurrence_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("payment_occurrences.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    filename: Mapped[str | None] = mapped_column(String(180))
    content_type: Mapped[str | None] = mapped_column(String(32))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    # Ordinary metadata reads never load the document itself.
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
