from contextlib import asynccontextmanager

from asyncpg import PostgresError
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.budget import router as budget_router
from app.api.dependencies import reject_unknown_query_parameters, require_allowed_origin
from app.api.mfa import internal_router as telegram_auth_router
from app.api.mfa import router as mfa_router
from app.api.payment_lifecycle import router as lifecycle_router
from app.api.payments import router as payments_router
from app.api.receipts import router as receipts_router
from app.api.registration import router as registration_router
from app.api.users import router as users_router
from app.core.config import Settings, settings
from app.core.exceptions import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.db.session import Database


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or settings
    database = Database(config.database_url) if config.database_url else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if database is None:
            raise RuntimeError("Set DATABASE_URL in backend/.env before starting the API")
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(
        title=config.app_name,
        version="0.1.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = config
    app.state.database = database
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.middleware("http")
    async def private_responses(request, call_next):
        if request.url.path.startswith("/api/v1/") and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            try:
                require_allowed_origin(request)
            except StarletteHTTPException as exc:
                response = await http_exception_handler(request, exc)
                response.headers["Cache-Control"] = "no-store"
                return response
        response = await call_next(request)
        if request.url.path.startswith(
            (
                "/api/v1/auth",
                "/api/v1/users",
                "/api/v1/audit-events",
                "/api/v1/payments",
                "/api/v1/recurring-payments",
                "/api/v1/payment-occurrences",
                "/api/v1/payment-receipts",
                "/api/v1/one-time-payments",
                "/api/v1/registration",
                "/internal/v1/telegram-auth",
            )
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Filename"],
        expose_headers=["Retry-After"],
    )
    api_router = APIRouter(
        prefix="/api/v1", dependencies=[Depends(reject_unknown_query_parameters)]
    )

    @api_router.get("/health", tags=["service"])
    async def health():
        return {"status": "ok"}

    @api_router.get("/ready", tags=["service"])
    async def ready():
        if database is None:
            raise HTTPException(status_code=503)
        try:
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError):
            raise HTTPException(status_code=503) from None
        return {"status": "ok"}

    api_router.include_router(auth_router)
    api_router.include_router(mfa_router)
    api_router.include_router(audit_router)
    api_router.include_router(budget_router)
    api_router.include_router(receipts_router)
    api_router.include_router(registration_router)
    api_router.include_router(users_router)
    api_router.include_router(payments_router)
    api_router.include_router(lifecycle_router)
    app.include_router(api_router)
    app.include_router(telegram_auth_router)
    return app


app = create_app()
