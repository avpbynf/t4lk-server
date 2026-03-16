"""Shared utility functions for the STT API."""

import uuid
from collections.abc import Sequence
from typing import Any


def humanize_validation_error(errors: Sequence[Any]) -> str:
    """Convert Pydantic validation errors into a human-readable message.

    Takes the list of error dicts from a RequestValidationError and returns
    a single string suitable for API error responses.

    Args:
        errors: List of error dictionaries from RequestValidationError.errors().

    Returns:
        A semicolon-separated string of "field: message" entries.
    """
    parts: list[str] = []
    for err in errors:
        loc = " -> ".join(str(x) for x in err.get("loc", []))
        msg = err.get("msg", "Unknown error")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


def generate_otel_trace_id() -> str:
    """Generate a 32-character hex trace ID compatible with OpenTelemetry.

    Uses UUID4 to produce a 128-bit random value, formatted as a lowercase
    hex string without hyphens (matching the W3C Trace Context spec).

    Returns:
        A 32-character lowercase hexadecimal string.
    """
    return uuid.uuid4().hex
