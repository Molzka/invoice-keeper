from fastapi import APIRouter, FastAPI

from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    redoc_url=None,
)

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health", tags=["service"])
async def health():
    return {"status": "ok"}


app.include_router(api_router)
