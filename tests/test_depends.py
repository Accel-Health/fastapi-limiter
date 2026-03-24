from time import sleep

import pytest
import redis as pyredis
from starlette.testclient import TestClient

from examples.main import app


@pytest.fixture(autouse=True)
def flush_redis():
    """Flush all Redis keys before each test to avoid rate limit bleed between tests."""
    r = pyredis.from_url("redis://localhost:6379")
    r.flushdb()
    r.close()


def test_limiter():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200

        response = client.get("/")
        assert response.status_code == 200

        response = client.get("/")
        assert response.status_code == 429

        response = client.post("/")
        assert response.status_code == 200

        response = client.post("/")
        assert response.status_code == 429
        sleep(5)

        response = client.get("/")
        assert response.status_code == 200

        response = client.post("/")
        assert response.status_code == 200


def test_limiter_multiple():
    with TestClient(app) as client:
        response = client.get("/multiple")
        assert response.status_code == 200

        response = client.get("/multiple")
        assert response.status_code == 429
        sleep(5)

        response = client.get("/multiple")
        assert response.status_code == 200

        response = client.get("/multiple")
        assert response.status_code == 429
        sleep(10)

        response = client.get("/multiple")
        assert response.status_code == 200


def test_limiter_websockets():
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text("Hi")
            data = ws.receive_text()
            assert data == "Hello, world"

            ws.send_text("Hi")
            data = ws.receive_text()
            assert data == "Hello again"

            ws.send_text("Hi 2")
            data = ws.receive_text()
            assert data == "Hello, world"
