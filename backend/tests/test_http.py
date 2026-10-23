import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_liveness_and_http_errors_do_not_need_a_database_connection():
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused_test",
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        health = await client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        missing = await client.get("/api/v1/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "NOT_FOUND"
        assert set(missing.json()["error"]) == {"code", "message", "details"}
        wrong_method = await client.post("/api/v1/health")
        assert wrong_method.status_code == 405
        assert wrong_method.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
        assert "GET" in wrong_method.headers["allow"]


@pytest.mark.asyncio
async def test_unexpected_errors_do_not_expose_internal_details():
    app = create_app(Settings(_env_file=None, app_env="test", database_url=None))

    @app.get("/test-internal-error")
    async def internal_error():
        raise RuntimeError("sensitive-internal-detail")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/test-internal-error")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "sensitive-internal-detail" not in response.text
