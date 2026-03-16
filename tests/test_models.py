"""Tests for rest.models — Pydantic models, constants and serialization."""

import pytest
from pydantic import ValidationError

from rest.models import ApiErrorModel, ErrorResponse, HealthResponse
from rest.v1.transcriptions.models import (
    ALLOWED_EXTENSIONS,
    ALLOWED_RESPONSE_FORMATS,
    MAX_UPLOAD_SIZE,
    SegmentInfo,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamSegmentEvent,
    TranscriptionResponse,
    VerboseTranscriptionResponse,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_max_upload_size_is_25_mb():
    # Arrange / Act / Assert
    assert MAX_UPLOAD_SIZE == 25 * 1024 * 1024


def test_allowed_extensions_contains_expected_formats():
    expected = {"wav", "mp3", "mp4", "m4a", "ogg", "flac", "webm"}
    assert ALLOWED_EXTENSIONS == expected


def test_allowed_response_formats_contains_expected_values():
    expected = {"json", "text", "verbose_json", "srt", "vtt"}
    assert ALLOWED_RESPONSE_FORMATS == expected


# ---------------------------------------------------------------------------
# SegmentInfo
# ---------------------------------------------------------------------------


def test_segment_info_creation():
    # Arrange
    seg = SegmentInfo(index=0, start=0.0, end=2.5, text=" Bonjour")

    # Assert
    assert seg.index == 0
    assert seg.start == 0.0
    assert seg.end == 2.5
    assert seg.text == " Bonjour"


def test_segment_info_is_frozen():
    seg = SegmentInfo(index=0, start=0.0, end=2.5, text=" Bonjour")

    with pytest.raises((TypeError, ValidationError)):
        seg.text = "mutated"  # type: ignore[misc]


def test_segment_info_serialization():
    seg = SegmentInfo(index=1, start=1.0, end=3.0, text="hello")
    data = seg.model_dump_json()

    assert '"index":1' in data
    assert '"start":1.0' in data
    assert '"end":3.0' in data
    assert '"text":"hello"' in data


def test_segment_info_requires_all_fields():
    with pytest.raises(ValidationError):
        SegmentInfo(index=0, start=0.0)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TranscriptionResponse
# ---------------------------------------------------------------------------


def test_transcription_response_creation():
    resp = TranscriptionResponse(text="hello world")
    assert resp.text == "hello world"


def test_transcription_response_is_frozen():
    resp = TranscriptionResponse(text="hello")

    with pytest.raises((TypeError, ValidationError)):
        resp.text = "mutated"  # type: ignore[misc]


def test_transcription_response_serialization():
    resp = TranscriptionResponse(text="test")
    assert '"text":"test"' in resp.model_dump_json()


# ---------------------------------------------------------------------------
# VerboseTranscriptionResponse
# ---------------------------------------------------------------------------


def test_verbose_transcription_response_creation():
    seg = SegmentInfo(index=0, start=0.0, end=2.0, text="hi")
    resp = VerboseTranscriptionResponse(
        task="transcribe",
        language="fr",
        duration=2.0,
        text="hi",
        segments=[seg],
    )

    assert resp.task == "transcribe"
    assert resp.language == "fr"
    assert resp.duration == 2.0
    assert len(resp.segments) == 1


def test_verbose_transcription_response_is_frozen():
    resp = VerboseTranscriptionResponse(
        task="transcribe", language="fr", duration=1.0, text="hi", segments=[]
    )

    with pytest.raises((TypeError, ValidationError)):
        resp.text = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StreamSegmentEvent
# ---------------------------------------------------------------------------


def test_stream_segment_event_creation():
    evt = StreamSegmentEvent(index=0, start=0.0, end=1.0, text="seg")

    assert evt.index == 0
    assert evt.text == "seg"


def test_stream_segment_event_is_frozen():
    evt = StreamSegmentEvent(index=0, start=0.0, end=1.0, text="seg")

    with pytest.raises((TypeError, ValidationError)):
        evt.text = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StreamDoneEvent
# ---------------------------------------------------------------------------


def test_stream_done_event_creation():
    evt = StreamDoneEvent(text="full text", language="fr", duration=5.0)

    assert evt.text == "full text"
    assert evt.language == "fr"
    assert evt.duration == 5.0


def test_stream_done_event_is_frozen():
    evt = StreamDoneEvent(text="t", language="fr", duration=1.0)

    with pytest.raises((TypeError, ValidationError)):
        evt.text = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StreamErrorEvent
# ---------------------------------------------------------------------------


def test_stream_error_event_creation():
    evt = StreamErrorEvent(message="boom", type="RuntimeError")

    assert evt.message == "boom"
    assert evt.type == "RuntimeError"


def test_stream_error_event_is_frozen():
    evt = StreamErrorEvent(message="boom", type="RuntimeError")

    with pytest.raises((TypeError, ValidationError)):
        evt.message = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HealthResponse
# ---------------------------------------------------------------------------


def test_health_response_creation():
    resp = HealthResponse(status="ok", model_loaded=True, device="cuda", queue_size=0)

    assert resp.status == "ok"
    assert resp.model_loaded is True
    assert resp.device == "cuda"
    assert resp.queue_size == 0


def test_health_response_is_frozen():
    resp = HealthResponse(status="ok", model_loaded=True, device="cuda", queue_size=0)

    with pytest.raises((TypeError, ValidationError)):
        resp.status = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ErrorResponse
# ---------------------------------------------------------------------------


def test_error_response_creation():
    err = ErrorResponse(detail="something went wrong")
    assert err.detail == "something went wrong"


def test_error_response_is_frozen():
    err = ErrorResponse(detail="oops")

    with pytest.raises((TypeError, ValidationError)):
        err.detail = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ApiErrorModel
# ---------------------------------------------------------------------------


def test_api_error_model():
    """ApiErrorModel captures error details with optional trace ID."""
    error = ApiErrorModel(
        status=400,
        message="Bad request",
        type="InvalidAudioError",
        trace_id="abc123",
    )
    assert error.status == 400
    assert error.message == "Bad request"
    assert error.type == "InvalidAudioError"
    assert error.trace_id == "abc123"


def test_api_error_model_no_trace_id():
    """ApiErrorModel works without trace_id."""
    error = ApiErrorModel(
        status=500,
        message="Internal server error",
        type="Exception",
    )
    assert error.trace_id is None
