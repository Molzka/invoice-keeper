import re
import unicodedata
from urllib.parse import unquote
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.delivery.locking import lock_payments
from app.models.payment_occurrence import PaymentOccurrence
from app.models.payment_receipt import MAX_RECEIPT_BYTES, PaymentReceipt
from app.models.recurring_payment import RecurringPayment
from app.models.user import User
from app.services.audit import record_audit_event
from app.services.errors import api_error

FILE_SIGNATURES = {
    "application/pdf": (b"%PDF-", ".pdf"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
}


def receipt_data(receipt: PaymentReceipt) -> dict:
    return {
        "id": receipt.id,
        "kind": receipt.kind,
        "url": receipt.url,
        "filename": receipt.filename,
        "content_type": receipt.content_type,
        "size_bytes": receipt.size_bytes,
        "uploaded_at": receipt.uploaded_at,
    }


def receipt_filename(encoded_name: str | None, content_type: str) -> str:
    suffix = FILE_SIGNATURES[content_type][1]
    if not encoded_name:
        return f"receipt{suffix}"
    # The original name is display-only: never a storage path or response header.
    name = unquote(encoded_name, errors="replace").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if not unicodedata.category(char).startswith("C"))
    name = name.strip(" .")[:160]
    if not name:
        return f"receipt{suffix}"
    # Keep a truthful extension even when the browser provides a misleading one.
    stem = re.sub(r"\.[^.]*$", "", name).strip(" .") or "receipt"
    return f"{stem}{suffix}"


def validate_receipt_file(data: bytes, content_type: str) -> None:
    if content_type not in FILE_SIGNATURES:
        raise api_error(415, "UNSUPPORTED_RECEIPT_TYPE", "Разрешены PDF, PNG и JPEG")
    if len(data) > MAX_RECEIPT_BYTES:
        raise api_error(413, "RECEIPT_TOO_LARGE", "Размер чека не должен превышать 5 МиБ")
    if not data or not data.startswith(FILE_SIGNATURES[content_type][0]):
        message = "Содержимое файла не соответствует выбранному формату PDF, PNG или JPEG"
        raise api_error(
            422,
            "VALIDATION_ERROR",
            message,
            details=[{"field": "file", "code": "INVALID_RECEIPT_FILE", "message": message}],
        )


async def _require_occurrence(db: AsyncSession, occurrence_id: UUID) -> None:
    if (
        await db.scalar(select(PaymentOccurrence.id).where(PaymentOccurrence.id == occurrence_id))
        is None
    ):
        raise api_error(404, "PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")


async def get_receipt(db: AsyncSession, occurrence_id: UUID) -> dict | None:
    await _require_occurrence(db, occurrence_id)
    receipt = await db.scalar(
        select(PaymentReceipt).where(PaymentReceipt.occurrence_id == occurrence_id)
    )
    return receipt_data(receipt) if receipt is not None else None


async def get_receipt_file(db: AsyncSession, occurrence_id: UUID) -> tuple[bytes, str]:
    await _require_occurrence(db, occurrence_id)
    row = (
        await db.execute(
            select(PaymentReceipt.data, PaymentReceipt.content_type).where(
                PaymentReceipt.occurrence_id == occurrence_id,
                PaymentReceipt.kind == "file",
            )
        )
    ).one_or_none()
    if row is None:
        raise api_error(404, "RECEIPT_FILE_NOT_FOUND", "Файл чека не найден")
    return row.data, row.content_type


async def _lock_occurrence(
    db: AsyncSession, occurrence_id: UUID
) -> tuple[RecurringPayment, PaymentOccurrence]:
    await lock_payments(db)
    payment_id = await db.scalar(
        select(PaymentOccurrence.recurring_payment_id).where(PaymentOccurrence.id == occurrence_id)
    )
    if payment_id is None:
        raise api_error(404, "PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")
    payment = await db.scalar(
        select(RecurringPayment)
        .where(RecurringPayment.id == payment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    occurrence = await db.scalar(
        select(PaymentOccurrence)
        .where(PaymentOccurrence.id == occurrence_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if payment is None or occurrence is None:
        raise api_error(404, "PAYMENT_OCCURRENCE_NOT_FOUND", "Период платежа не найден")
    if occurrence.is_cancelled:
        raise api_error(
            409,
            "PAYMENT_CANCELLED",
            "Период удалён. Подтверждение сохранено в истории только для просмотра.",
        )
    return payment, occurrence


def _audit_receipt(
    db: AsyncSession,
    *,
    actor: User,
    payment: RecurringPayment,
    occurrence: PaymentOccurrence,
    before: str | None,
    after: str | None,
    deleted: bool = False,
) -> None:
    labels = {None: None, "link": "Ссылка", "file": "Файл"}
    record_audit_event(
        db,
        actor=actor,
        action="payment.receipt_deleted" if deleted else "payment.receipt_updated",
        entity_type="payment",
        entity_id=payment.id,
        entity_title=payment.title,
        changes=[
            {
                "field": "due_date",
                "label": "Период со сроком",
                "before": None,
                "after": occurrence.due_date.isoformat(),
            },
            {"field": "receipt", "label": "Чек", "before": labels[before], "after": labels[after]},
        ],
    )


async def save_receipt(
    db: AsyncSession,
    occurrence_id: UUID,
    *,
    actor: User,
    url: str | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    encoded_filename: str | None = None,
) -> dict:
    if url is not None:
        kind, filename, size_bytes = "link", None, None
        data, content_type = None, None
    else:
        validate_receipt_file(data or b"", content_type or "")
        kind, filename, size_bytes = (
            "file",
            receipt_filename(encoded_filename, content_type),
            len(data),
        )
    payment, occurrence = await _lock_occurrence(db, occurrence_id)
    receipt = await db.scalar(
        select(PaymentReceipt)
        .where(PaymentReceipt.occurrence_id == occurrence_id)
        .with_for_update()
    )
    previous_kind = receipt.kind if receipt is not None else None
    if receipt is not None:
        unchanged = (
            receipt.kind == kind
            and receipt.url == url
            and receipt.filename == filename
            and receipt.content_type == content_type
            and receipt.size_bytes == size_bytes
        )
        if unchanged and kind == "file":
            unchanged = (
                await db.scalar(select(PaymentReceipt.data).where(PaymentReceipt.id == receipt.id))
                == data
            )
        if unchanged:
            await db.commit()
            return receipt_data(receipt)
    else:
        receipt = PaymentReceipt(occurrence_id=occurrence_id)
        db.add(receipt)
    receipt.kind = kind
    receipt.url = url
    receipt.filename = filename
    receipt.content_type = content_type
    receipt.size_bytes = size_bytes
    receipt.data = data
    receipt.uploaded_at = utc_now()
    _audit_receipt(
        db, actor=actor, payment=payment, occurrence=occurrence, before=previous_kind, after=kind
    )
    await db.commit()
    return receipt_data(receipt)


async def delete_receipt(db: AsyncSession, occurrence_id: UUID, *, actor: User) -> None:
    payment, occurrence = await _lock_occurrence(db, occurrence_id)
    receipt = await db.scalar(
        select(PaymentReceipt)
        .where(PaymentReceipt.occurrence_id == occurrence_id)
        .with_for_update()
    )
    if receipt is not None:
        _audit_receipt(
            db,
            actor=actor,
            payment=payment,
            occurrence=occurrence,
            before=receipt.kind,
            after=None,
            deleted=True,
        )
        await db.delete(receipt)
    await db.commit()


async def list_receipts(db: AsyncSession, *, today, currency, kind, query, limit, offset) -> dict:
    from app.services.payments import occurrence_data

    conditions = [PaymentOccurrence.is_cancelled.is_(False)]
    if currency is not None:
        conditions.append(PaymentOccurrence.currency == currency)
    if kind == "missing":
        conditions.append(PaymentReceipt.id.is_(None))
    elif kind in {"file", "link"}:
        conditions.append(PaymentReceipt.kind == kind)
    if query.strip():
        value = (
            "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        conditions.append(
            or_(
                RecurringPayment.title.ilike(value, escape="\\"),
                PaymentReceipt.filename.ilike(value, escape="\\"),
                PaymentReceipt.url.ilike(value, escape="\\"),
            )
        )
    query_rows = (
        select(PaymentOccurrence, RecurringPayment, PaymentReceipt)
        .join(RecurringPayment, RecurringPayment.id == PaymentOccurrence.recurring_payment_id)
        .outerjoin(PaymentReceipt, PaymentReceipt.occurrence_id == PaymentOccurrence.id)
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(query_rows.subquery()))
    rows = await db.execute(
        query_rows.order_by(PaymentOccurrence.due_date.desc(), PaymentOccurrence.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [
            {
                "occurrence": occurrence_data(payment, occurrence, today),
                "receipt": receipt_data(receipt) if receipt is not None else None,
            }
            for occurrence, payment, receipt in rows
        ],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }
