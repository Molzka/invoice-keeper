from contextlib import asynccontextmanager

from asyncpg import PostgresError
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.auth import router as auth_router
from app.api.dependencies import reject_unknown_query_parameters, require_allowed_origin
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
        if request.url.path.startswith(("/api/v1/auth", "/api/v1/users")):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
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
    api_router.include_router(users_router)
    app.include_router(api_router)
    return app


app = create_app()
