"""Tests for rest.utils — humanize_validation_error, generate_otel_trace_id."""

from rest.utils import generate_otel_trace_id, humanize_validation_error

# ---------------------------------------------------------------------------
# humanize_validation_error
# ---------------------------------------------------------------------------


def test_humanize_single_error():
    """Single validation error produces a clean message."""
    errors = [{"loc": ["query", "count"], "msg": "value is not a valid integer"}]
    result = humanize_validation_error(errors)
    assert result == "query -> count: value is not a valid integer"


def test_humanize_multiple_errors():
    """Multiple errors are joined with semicolons."""
    errors = [
        {"loc": ["body", "name"], "msg": "field required"},
        {"loc": ["body", "age"], "msg": "value is not a valid integer"},
    ]
    result = humanize_validation_error(errors)
    assert "body -> name: field required" in result
    assert "body -> age: value is not a valid integer" in result
    assert "; " in result


def test_humanize_empty_list():
    """Empty error list returns empty string."""
    assert humanize_validation_error([]) == ""


def test_humanize_missing_loc():
    """Error without loc uses message only."""
    errors = [{"msg": "something went wrong"}]
    result = humanize_validation_error(errors)
    assert result == "something went wrong"


def test_humanize_missing_msg():
    """Error without msg uses fallback."""
    errors = [{"loc": ["field"]}]
    result = humanize_validation_error(errors)
    assert result == "field: Unknown error"


# ---------------------------------------------------------------------------
# generate_otel_trace_id
# ---------------------------------------------------------------------------


def test_generate_otel_trace_id_length():
    """Trace ID is exactly 32 hex characters."""
    trace_id = generate_otel_trace_id()
    assert len(trace_id) == 32


def test_generate_otel_trace_id_hex():
    """Trace ID contains only hex characters."""
    trace_id = generate_otel_trace_id()
    assert all(c in "0123456789abcdef" for c in trace_id)


def test_generate_otel_trace_id_unique():
    """Consecutive calls produce unique trace IDs."""
    ids = {generate_otel_trace_id() for _ in range(100)}
    assert len(ids) == 100
