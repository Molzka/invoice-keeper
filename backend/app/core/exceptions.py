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
    # Do not reflect input, ctx or error messages: they can contain passwords.
    details = [{"location": list(error["loc"]), "type": error["type"]} for error in exc.errors()]
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
