from contextlib import asynccontextmanager

import pytest
import redis as pyredis
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, Request, Response
from starlette.testclient import TestClient

from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter


@pytest.fixture(autouse=True)
def flush_redis():
    """Flush all Redis keys before each test to avoid rate limit bleed between tests."""
    r = pyredis.from_url("redis://localhost:6379")
    r.flushdb()
    r.close()


def test_retry_after_header():
    """429 responses should include a Retry-After header with seconds remaining."""
    from examples.main import app

    with TestClient(app) as client:
        client.get("/")
        client.get("/")
        response = client.get("/")
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        retry_after = int(response.headers["Retry-After"])
        assert 1 <= retry_after <= 5


def test_x_forwarded_for_identifier():
    """Requests with X-Forwarded-For should be identified by the first IP in the header."""
    from examples.main import app

    with TestClient(app) as client:
        # Exhaust the limit for the forwarded IP
        client.get("/", headers={"X-Forwarded-For": "1.2.3.4"})
        client.get("/", headers={"X-Forwarded-For": "1.2.3.4"})
        response = client.get("/", headers={"X-Forwarded-For": "1.2.3.4"})
        assert response.status_code == 429

        # A different forwarded IP should not be rate limited
        response = client.get("/", headers={"X-Forwarded-For": "5.6.7.8"})
        assert response.status_code == 200


def test_x_forwarded_for_uses_first_ip():
    """When X-Forwarded-For contains multiple IPs, only the first (client) IP is used."""
    from examples.main import app

    with TestClient(app) as client:
        client.get("/", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})
        client.get("/", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.2"})
        # Same first IP, different proxy IPs — should still count as same client
        response = client.get("/", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.3"})
        assert response.status_code == 429


def test_custom_identifier():
    """Per-route identifier override should be used instead of the global default."""

    async def custom_identifier(request):
        return request.headers.get("X-API-Key", "anonymous")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        redis_connection = aioredis.from_url("redis://localhost:6379", encoding="utf8")
        await FastAPILimiter.init(redis_connection)
        yield
        await FastAPILimiter.close()

    app = FastAPI(lifespan=lifespan)

    @app.get(
        "/custom-id",
        dependencies=[Depends(RateLimiter(times=1, seconds=5, identifier=custom_identifier))],
    )
    async def custom_id_route():
        return {"msg": "ok"}

    with TestClient(app) as client:
        # First key hits limit
        response = client.get("/custom-id", headers={"X-API-Key": "key-a"})
        assert response.status_code == 200
        response = client.get("/custom-id", headers={"X-API-Key": "key-a"})
        assert response.status_code == 429

        # Different key is independent
        response = client.get("/custom-id", headers={"X-API-Key": "key-b"})
        assert response.status_code == 200


def test_custom_callback():
    """Per-route callback override should be called instead of the global default."""

    async def custom_callback(request: Request, response: Response, pexpire: int):
        response.status_code = 503
        response.headers["X-Custom"] = "rate-limited"
        return response

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        redis_connection = aioredis.from_url("redis://localhost:6379", encoding="utf8")
        await FastAPILimiter.init(redis_connection)
        yield
        await FastAPILimiter.close()

    app = FastAPI(lifespan=lifespan)

    @app.get(
        "/custom-cb",
        dependencies=[Depends(RateLimiter(times=1, seconds=5, callback=custom_callback))],
    )
    async def custom_cb_route():
        return {"msg": "ok"}

    with TestClient(app) as client:
        response = client.get("/custom-cb")
        assert response.status_code == 200

        response = client.get("/custom-cb")
        assert response.status_code == 503
        assert response.headers.get("X-Custom") == "rate-limited"


def test_not_initialized_error():
    """Calling RateLimiter without FastAPILimiter.init should raise an error."""
    app = FastAPI()

    @app.get("/", dependencies=[Depends(RateLimiter(times=1, seconds=5))])
    async def index():
        return {"msg": "ok"}

    with TestClient(app, raise_server_exceptions=False) as client:
        # FastAPILimiter.init was never called, so redis is None
        saved_redis = FastAPILimiter.redis
        FastAPILimiter.redis = None
        try:
            response = client.get("/")
            assert response.status_code == 500
        finally:
            FastAPILimiter.redis = saved_redis
