"""Tests for rest.middlewares — execution time, trace, access log, exception handler."""

import logging

import httpx
from fastapi import FastAPI

from rest.exceptions import InvalidAudioError, QueueTimeoutError, TranscriptionError
from rest.middlewares import (
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

    with caplog.at_level(logging.INFO, logger="rest.middlewares"):
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

    with caplog.at_level(logging.INFO, logger="rest.middlewares"):
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
    body = response.json()
    assert body["status"] == 503
    assert "timeout" in body["message"]
    assert body["type"] == "QueueTimeoutError"


async def test_invalid_audio_error_returns_400():
    async with await _make_raising_app(InvalidAudioError("bad file")) as client:
        response = await client.get("/error")

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == 400
    assert "bad file" in body["message"]
    assert body["type"] == "InvalidAudioError"


async def test_transcription_error_returns_500():
    async with await _make_raising_app(TranscriptionError("model failed")) as client:
        response = await client.get("/error")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == 500
    assert "model failed" in body["message"]
    assert body["type"] == "TranscriptionError"


async def test_generic_exception_returns_500():
    async with await _make_raising_app(RuntimeError("unexpected")) as client:
        response = await client.get("/error")

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == 500
    assert body["message"] == "Internal server error"
    assert body["type"] == "RuntimeError"


async def test_exception_response_has_api_error_model_shape():
    async with await _make_raising_app(InvalidAudioError("bad")) as client:
        response = await client.get("/error")

    body = response.json()
    assert "status" in body
    assert "message" in body
    assert "type" in body
    assert "trace_id" in body


async def test_http_exception_preserves_status_code():
    """HTTPException handler preserves the original status code."""
    from starlette.exceptions import HTTPException as StarletteHTTPException

    async with await _make_raising_app(
        StarletteHTTPException(status_code=404, detail="Not found")
    ) as client:
        response = await client.get("/error")

    assert response.status_code == 404
    body = response.json()
    assert body["status"] == 404
    assert body["message"] == "Not found"
    assert body["type"] == "HTTPException"


async def test_validation_error_returns_422():
    """RequestValidationError is caught and returns 422 with humanised message."""
    app = FastAPI()
    add_exception_middleware(app)

    @app.get("/validate")
    async def validate(count: int):
        return {"count": count}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/validate?count=abc")

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == 422
    assert body["type"] == "RequestValidationError"
    assert "message" in body
