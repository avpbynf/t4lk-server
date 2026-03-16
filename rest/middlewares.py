"""Middleware stack for the STT server."""

import logging
import time
from collections.abc import Callable
from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from rest.exceptions import (
    InvalidAudioError,
    QueueTimeoutError,
    STTError,
    TranscriptionError,
)
from rest.models import ApiErrorModel
from rest.utils import generate_otel_trace_id

logger = logging.getLogger(__name__)


class ExecutionTimeMiddleware(BaseHTTPMiddleware):
    """Measures wall-clock time and adds X-Execution-Time header.

    This middleware is outermost and therefore wraps all others.
    The header value is expressed in milliseconds with one decimal place.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and attach timing header.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            Response with X-Execution-Time header set.
        """
        start = time.perf_counter()
        response = cast(Response, await call_next(request))
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Execution-Time"] = f"{elapsed_ms:.1f}ms"
        return response


class TraceMiddleware(BaseHTTPMiddleware):
    """Generates a unique trace ID for each request.

    Stores the ID in request.state.trace_id and echoes it back via the
    X-Request-Id response header for client-side correlation.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Attach a trace ID to the request and response.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            Response with X-Request-Id header set.
        """
        trace_id = generate_otel_trace_id()
        request.state.trace_id = trace_id
        response = cast(Response, await call_next(request))
        response.headers["X-Request-Id"] = trace_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Logs one line per request with method, path, status, and duration.

    Also appends STT-specific fields when present in request.state:
    - audio_duration_ms: duration of the audio file in milliseconds
    - model: Whisper model name used for this request
    - language: detected or requested language code
    - queue_wait_ms: time spent waiting for a GPU slot

    Log format example::

        POST /v1/audio/transcriptions 200 1234.5ms
        [trace_id=abc123 audio=5000ms model=large-v3 lang=fr]
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log the request after it completes.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            Unmodified response from the next handler.
        """
        start = time.perf_counter()
        response = cast(Response, await call_next(request))
        elapsed_ms = (time.perf_counter() - start) * 1000

        parts: list[str] = []

        trace_id = getattr(request.state, "trace_id", None)
        if trace_id:
            parts.append(f"trace_id={trace_id}")

        audio_duration_ms = getattr(request.state, "audio_duration_ms", None)
        if audio_duration_ms is not None:
            parts.append(f"audio={audio_duration_ms:.0f}ms")

        model = getattr(request.state, "model", None)
        if model:
            parts.append(f"model={model}")

        language = getattr(request.state, "language", None)
        if language:
            parts.append(f"lang={language}")

        queue_wait_ms = getattr(request.state, "queue_wait_ms", None)
        if queue_wait_ms is not None:
            parts.append(f"queue={queue_wait_ms:.0f}ms")

        extra = f" [{' '.join(parts)}]" if parts else ""
        logger.info(
            "%s %s %d %.1fms%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            extra,
        )
        return response


def add_exception_middleware(app: FastAPI) -> None:
    """Register exception handlers that return uniform ApiErrorModel responses.

    Registers three handlers (order matters for FastAPI resolution):
    1. RequestValidationError -> 422 with humanised field errors
    2. HTTPException -> preserves the original status code
    3. Exception (catch-all) -> maps STTError subclasses to codes, else 500

    Args:
        app: The FastAPI application instance to register the handlers on.
    """

    def _build_error(
        status_code: int,
        message: str,
        error_type: str,
        trace_id: str | None,
    ) -> JSONResponse:
        body = ApiErrorModel(
            status=status_code,
            message=message,
            type=error_type,
            trace_id=trace_id,
        )
        return JSONResponse(
            status_code=status_code,
            content=body.model_dump(),
            headers={"X-Request-Id": trace_id} if trace_id else {},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Return a 422 response with humanised validation errors.

        Args:
            request: The request that triggered the validation error.
            exc: The validation exception raised by Pydantic/FastAPI.

        Returns:
            JSONResponse with 422 status and ApiErrorModel body.
        """
        from rest.utils import humanize_validation_error

        trace_id = getattr(request.state, "trace_id", None)
        message = humanize_validation_error(exc.errors())
        logger.warning(
            "Validation error 422 for %s %s [trace_id=%s]: %s",
            request.method,
            request.url.path,
            trace_id,
            message,
        )
        return _build_error(422, message, "RequestValidationError", trace_id)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Return an ApiErrorModel response for explicit HTTP exceptions.

        Args:
            request: The request that triggered the exception.
            exc: The HTTP exception with status_code and detail.

        Returns:
            JSONResponse preserving the original status code.
        """
        trace_id = getattr(request.state, "trace_id", None)
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        if exc.status_code >= 500:
            logger.error(
                "HTTP %d for %s %s [trace_id=%s]: %s",
                exc.status_code,
                request.method,
                request.url.path,
                trace_id,
                detail,
            )
        return _build_error(exc.status_code, detail, "HTTPException", trace_id)

    @app.exception_handler(Exception)
    async def _handle_exception(request: Request, exc: Exception) -> JSONResponse:
        """Return a JSON error response for any unhandled exception.

        Args:
            request: The request that triggered the exception.
            exc: The unhandled exception.

        Returns:
            JSONResponse with an appropriate status code and ApiErrorModel body.
        """
        trace_id = getattr(request.state, "trace_id", None)

        if isinstance(exc, QueueTimeoutError):
            status_code = 503
            detail = exc.message
        elif isinstance(exc, InvalidAudioError):
            status_code = 400
            detail = exc.message
        elif isinstance(exc, TranscriptionError):
            status_code = 500
            detail = exc.message
        elif isinstance(exc, STTError):
            status_code = 500
            detail = exc.message
        else:
            status_code = 500
            detail = "Internal server error"
            logger.exception(
                "Unhandled exception [trace_id=%s]: %s",
                trace_id,
                exc,
            )

        if status_code >= 500:
            logger.error(
                "Error %d for %s %s [trace_id=%s]: %s",
                status_code,
                request.method,
                request.url.path,
                trace_id,
                detail,
            )

        return _build_error(status_code, detail, type(exc).__name__, trace_id)
