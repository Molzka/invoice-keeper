import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.dependencies import CurrentUser, DbSession, require_csrf
from app.models.payment_receipt import MAX_RECEIPT_BYTES
from app.schemas.receipts import PaymentReceiptRead, ReceiptLinkUpdate
from app.services.errors import api_error
from app.services.receipts import (
    FILE_SIGNATURES,
    delete_receipt,
    get_receipt,
    get_receipt_file,
    save_receipt,
)

router = APIRouter(tags=["receipts"])
Csrf = Annotated[None, Depends(require_csrf)]
RECEIPT_PATH = "/payment-occurrences/{occurrence_id}/receipt"


async def _read_body(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise api_error(413, "RECEIPT_TOO_LARGE", "Размер чека не должен превышать 5 МиБ")
        body.extend(chunk)
    return bytes(body)


@router.get(RECEIPT_PATH, response_model=PaymentReceiptRead | None, summary="Получить чек периода")
async def read_receipt(occurrence_id: UUID, _user: CurrentUser, db: DbSession, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await get_receipt(db, occurrence_id)


@router.put(
    RECEIPT_PATH,
    response_model=PaymentReceiptRead,
    summary="Прикрепить HTTPS-ссылку или файл чека к периоду",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": ReceiptLinkUpdate.model_json_schema()},
                **{
                    mime: {"schema": {"type": "string", "format": "binary"}}
                    for mime in FILE_SIGNATURES
                },
            },
        }
    },
)
async def put_receipt(
    occurrence_id: UUID,
    request: Request,
    response: Response,
    user: CurrentUser,
    db: DbSession,
    _csrf: Csrf,
    x_filename: Annotated[str | None, Header(alias="X-Filename", max_length=4096)] = None,
):
    response.headers["Cache-Control"] = "no-store"
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        body = await _read_body(request, 64 * 1024)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise api_error(400, "INVALID_JSON", "Некорректный JSON") from None
        try:
            link = ReceiptLinkUpdate.model_validate(payload)
        except ValidationError as exc:
            raise RequestValidationError(
                [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
            ) from None
        return await save_receipt(db, occurrence_id, actor=user, url=link.url)
    if content_type not in FILE_SIGNATURES:
        raise api_error(
            415, "UNSUPPORTED_RECEIPT_TYPE", "Передайте HTTPS-ссылку в JSON или файл PDF, PNG, JPEG"
        )
    body = await _read_body(request, MAX_RECEIPT_BYTES)
    return await save_receipt(
        db,
        occurrence_id,
        actor=user,
        data=body,
        content_type=content_type,
        encoded_filename=x_filename,
    )


@router.delete(RECEIPT_PATH, status_code=204, summary="Удалить чек периода")
async def remove_receipt(occurrence_id: UUID, user: CurrentUser, db: DbSession, _csrf: Csrf):
    await delete_receipt(db, occurrence_id, actor=user)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get(RECEIPT_PATH + "/file", summary="Скачать прикреплённый файл чека")
async def download_receipt(occurrence_id: UUID, _user: CurrentUser, db: DbSession):
    data, content_type = await get_receipt_file(db, occurrence_id)
    suffix = FILE_SIGNATURES[content_type][1]
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="receipt{suffix}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "no-store",
        },
    )
