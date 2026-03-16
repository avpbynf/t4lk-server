"""Shared Pydantic models for the STT API."""

from pydantic import BaseModel, ConfigDict


class ApiErrorModel(BaseModel):
    """Uniform error envelope returned by all error responses.

    Follows the yjra pattern: structured error body with trace ID
    for client-side correlation and log lookup.
    """

    model_config = ConfigDict(frozen=True)

    status: int
    message: str
    type: str
    trace_id: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    model_config = ConfigDict(frozen=True)

    status: str
    model_loaded: bool
    device: str
    queue_size: int


class ErrorResponse(BaseModel):
    """Generic error response."""

    model_config = ConfigDict(frozen=True)

    detail: str
