from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERRORS_BY_STATUS = {
    401: ("AUTH_REQUIRED", "Требуется авторизация"),
    403: ("FORBIDDEN", "Доступ запрещён"),
    404: ("NOT_FOUND", "Маршрут не найден"),
    405: ("METHOD_NOT_ALLOWED", "HTTP-метод не поддерживается"),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Неподдерживаемый формат данных"),
    429: ("RATE_LIMITED", "Слишком много запросов"),
    503: ("SERVICE_UNAVAILABLE", "Сервис временно недоступен"),
}


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:

    if isinstance(exc.detail, dict) and "error" in exc.detail:
        error = exc.detail["error"]
    else:
        code, message = ERRORS_BY_STATUS.get(
            exc.status_code,
            ("HTTP_ERROR", "Ошибка HTTP-запроса"),
        )

        error = {
            "code": code,
            "message": message,
            "details": [],
        }

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error},
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = exc.errors()
    if any(error["type"] == "json_invalid" for error in errors):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_JSON",
                    "message": "Некорректный JSON",
                    "details": [],
                }
            },
        )
    # Build messages from known error codes, never from reflected input or ctx.
    details = [field_error(error) for error in errors]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Некорректные данные запроса",
                "details": details,
            }
        },
    )


def field_error(error: dict) -> dict[str, str]:
    location = list(error.get("loc", ()))
    source = location[0] if location else "body"
    path = location[1:] if source == "body" else location
    field = ".".join(str(part) for part in path) or "body"
    error_type = error["type"]
    messages = {
        "missing": ("REQUIRED", "Обязательное поле"),
        "string_too_short": ("TOO_SHORT", "Значение слишком короткое"),
        "string_too_long": ("TOO_LONG", "Значение слишком длинное"),
        "string_pattern_mismatch": ("INVALID_FORMAT", "Неверный формат поля"),
        "string_type": ("INVALID_TYPE", "Передайте строку"),
        "money_format": (
            "INVALID_MONEY_FORMAT",
            "Передайте положительную сумму строкой с двумя знаками после точки",
        ),
        "money_range": ("MONEY_OUT_OF_RANGE", "Сумма вне допустимого диапазона"),
        "payment_state": ("INVALID_PAYMENT_STATE", "Несогласованный статус оплаты и дата"),
        "uuid_parsing": ("INVALID_UUID", "Некорректный UUID"),
        "int_parsing": ("INVALID_INTEGER", "Передайте целое число"),
        "int_type": ("INVALID_INTEGER", "Передайте целое число"),
        "greater_than_equal": ("OUT_OF_RANGE", "Значение меньше допустимого"),
        "less_than_equal": ("OUT_OF_RANGE", "Значение больше допустимого"),
        "extra_forbidden": (
            "UNKNOWN_QUERY_PARAMETER" if source == "query" else "UNKNOWN_FIELD",
            "Неизвестный query-параметр" if source == "query" else "Неизвестное поле",
        ),
    }
    code, message = messages.get(error_type, ("INVALID_VALUE", "Некорректное значение поля"))
    return {"field": field, "code": code, "message": message}


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Внутренняя ошибка сервера",
                "details": [],
            }
        },
    )
