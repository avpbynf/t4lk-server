"""Tests for stt.middlewares — execution time, trace, access log, exception handler."""

import logging

import httpx
from fastapi import FastAPI

from stt.exceptions import InvalidAudioError, QueueTimeoutError, TranscriptionError
from stt.middlewares import (
    AccessLogMiddleware,
    ExecutionTimeMiddleware,
    TraceMiddleware,
    add_exception_middleware,
)

# ---------------------------------------------------------------------------
# Helpers: minimal test apps
# ---------------------------------------------------------------------------


def _make_app_with_execution_time() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ExecutionTimeMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def _make_app_with_trace() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def _make_app_with_access_log() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AccessLogMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def _make_app_with_exception_handler() -> FastAPI:
    app = FastAPI()
    add_exception_middleware(app)
    return app


# ---------------------------------------------------------------------------
# ExecutionTimeMiddleware
# ---------------------------------------------------------------------------


async def test_execution_time_header_present():
    # Arrange
    app = _make_app_with_execution_time()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Act
        response = await client.get("/ping")

    # Assert
    assert "x-execution-time" in response.headers
    header_value = response.headers["x-execution-time"]
    assert header_value.endswith("ms")
    elapsed = float(header_value.removesuffix("ms"))
    assert elapsed >= 0.0


# ---------------------------------------------------------------------------
# TraceMiddleware
# ---------------------------------------------------------------------------


async def test_trace_middleware_adds_x_request_id_header():
    app = _make_app_with_trace()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/ping")

    assert "x-request-id" in response.headers
    trace_id = response.headers["x-request-id"]
    # Trace ID is a 32-char hex string (16 bytes)
    assert len(trace_id) == 32
    assert all(c in "0123456789abcdef" for c in trace_id)


async def test_trace_middleware_unique_per_request():
    app = _make_app_with_trace()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r1 = await client.get("/ping")
        r2 = await client.get("/ping")

    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


# ---------------------------------------------------------------------------
# AccessLogMiddleware
# ---------------------------------------------------------------------------


async def test_access_log_contains_method_and_path(caplog):
    app = _make_app_with_access_log()

    with caplog.at_level(logging.INFO, logger="stt.middlewares"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/ping")

    assert response.status_code == 200
    assert any(
        "GET" in record.message and "/ping" in record.message
        for record in caplog.records
    )


async def test_access_log_contains_status_code(caplog):
    app = _make_app_with_access_log()

    with caplog.at_level(logging.INFO, logger="stt.middlewares"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/ping")

    assert any("200" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# add_exception_middleware
# ---------------------------------------------------------------------------


async def _make_raising_app(exc: Exception) -> httpx.AsyncClient:
    """Build a minimal app that raises *exc* on GET /error.

    Uses raise_app_exceptions=False so the custom exception handler registered
    via add_exception_middleware() intercepts the exception instead of httpx
    re-raising it before the response is returned.
    """
    app = FastAPI()
    add_exception_middleware(app)

    @app.get("/error")
    async def error():
        raise exc

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def test_queue_timeout_error_returns_503():
    # Arrange
    async with await _make_raising_app(QueueTimeoutError("timeout")) as client:
        # Act
        response = await client.get("/error")

    # Assert
    assert response.status_code == 503
    assert "timeout" in response.json()["detail"]


async def test_invalid_audio_error_returns_400():
    async with await _make_raising_app(InvalidAudioError("bad file")) as client:
        response = await client.get("/error")

    assert response.status_code == 400
    assert "bad file" in response.json()["detail"]


async def test_transcription_error_returns_500():
    async with await _make_raising_app(TranscriptionError("model failed")) as client:
        response = await client.get("/error")

    assert response.status_code == 500
    assert "model failed" in response.json()["detail"]


async def test_generic_exception_returns_500():
    async with await _make_raising_app(RuntimeError("unexpected")) as client:
        response = await client.get("/error")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


async def test_exception_response_has_detail_key():
    async with await _make_raising_app(InvalidAudioError("bad")) as client:
        response = await client.get("/error")

    assert "detail" in response.json()
