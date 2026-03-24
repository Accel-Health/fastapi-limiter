# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fastapi-limiter is a rate limiting library for FastAPI routes using Redis and Lua scripts. It provides `RateLimiter` (HTTP) and `WebSocketRateLimiter` dependencies that enforce request limits via a server-side Lua script executed atomically in Redis.

## Common Commands

- **Install dependencies:** `poetry install`
- **Run tests:** `make test` (requires a local Redis instance on port 6379)
- **Run a single test:** `pytest tests/test_depends.py::test_limiter`
- **Auto-format code:** `make style` (runs isort + black)
- **Lint/check:** `make check` (black --check, ruff, bandit)
- **Full CI locally:** `make ci` (runs check + test)

## Architecture

The library has two source files:

- **`fastapi_limiter/__init__.py`** — `FastAPILimiter` singleton class. Holds the Redis connection, Lua script SHA, and global defaults (identifier, callbacks). Must be initialized via `FastAPILimiter.init(redis)` during app lifespan.
- **`fastapi_limiter/depends.py`** — `RateLimiter` and `WebSocketRateLimiter` classes used as FastAPI dependencies. Rate limiting logic calls `redis.evalsha` with the preloaded Lua script. Handles `NoScriptError` by reloading the script automatically.

Key design points:
- `FastAPILimiter` uses **class-level state** (no instances) — all configuration is on the class itself.
- The Lua script atomically checks/increments a counter with a TTL, returning 0 (allowed) or the remaining TTL in ms (rejected).
- `RateLimiter.__call__` builds a unique Redis key from prefix, identifier, route index, and dependency index to support multiple limiters on the same route.
- `WebSocketRateLimiter` is called explicitly inside websocket handlers (not as a FastAPI dependency) and uses an optional `context_key` for the Redis key.

## Code Style

- Line length: 100 characters
- Formatting: black + isort (profile: black)
- Linting: ruff + bandit (bandit excludes tests/)
- Python target: 3.9+

## Testing

Tests are in `tests/test_depends.py` and use the example app from `examples/main.py` via Starlette's `TestClient`. Tests require a running Redis server on localhost:6379. Tests use `time.sleep()` to wait for rate limit windows to expire.
