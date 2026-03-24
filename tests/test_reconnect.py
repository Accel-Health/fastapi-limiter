from unittest.mock import AsyncMock, patch

import pytest
import redis as pyredis
from starlette.testclient import TestClient

from examples.main import app
from fastapi_limiter import FastAPILimiter


@pytest.fixture(autouse=True)
def flush_redis():
    """Flush all Redis keys before each test to avoid rate limit bleed between tests."""
    r = pyredis.from_url("redis://localhost:6379")
    r.flushdb()
    r.close()


def test_recovery_from_noscript_error():
    """After Redis restarts, the Lua script cache is lost. evalsha raises NoScriptError
    and _check should reload the script and retry."""
    with TestClient(app) as client:
        original_lua_sha = FastAPILimiter.lua_sha

        # Flush the script cache so the next evalsha raises NoScriptError
        client_sync = pyredis.from_url("redis://localhost:6379")
        client_sync.script_flush()
        client_sync.close()

        response = client.get("/")
        assert response.status_code == 200

        # Verify the script was reloaded (new SHA registered)
        assert FastAPILimiter.lua_sha is not None
        assert FastAPILimiter.lua_sha == original_lua_sha  # same script, same SHA


def test_recovery_from_connection_error():
    """When evalsha raises ConnectionError, _check should reload the script and retry."""
    with TestClient(app) as client:
        original_evalsha = FastAPILimiter.redis.evalsha
        call_count = 0

        async def evalsha_with_connection_error(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise pyredis.exceptions.ConnectionError("Connection lost")
            return await original_evalsha(*args, **kwargs)

        with patch.object(
            FastAPILimiter.redis, "evalsha", side_effect=evalsha_with_connection_error
        ):
            response = client.get("/")
            assert response.status_code == 200
            assert call_count == 2  # first call failed, second succeeded


def test_connection_error_not_suppressed_on_script_load():
    """If both evalsha AND script_load fail with ConnectionError, the error should propagate."""
    with TestClient(app, raise_server_exceptions=False) as client:
        with patch.object(
            FastAPILimiter.redis,
            "evalsha",
            side_effect=pyredis.exceptions.ConnectionError("Connection lost"),
        ), patch.object(
            FastAPILimiter.redis,
            "script_load",
            side_effect=pyredis.exceptions.ConnectionError("Still disconnected"),
        ):
            response = client.get("/")
            assert response.status_code == 500
