"""Tests for rest.engine: WhisperEngine transcription and streaming."""

import asyncio
from unittest.mock import MagicMock

import pytest

from rest.engine import SegmentResult, TranscriptionResult, WhisperEngine
from rest.exceptions import QueueTimeoutError, TranscriptionError
from rest.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**kwargs) -> Settings:
    defaults = dict(DEVICE="cpu", GPU_TIMEOUT=5, GPU_CONCURRENCY=1)
    defaults.update(kwargs)
    return Settings(**defaults)


def _make_mock_model():
    """Return a fresh mock model with predictable transcribe() output."""
    model = MagicMock()
    seg1 = MagicMock(start=0.0, end=2.5, text=" Bonjour")
    seg2 = MagicMock(start=2.5, end=5.0, text=" tout le monde")
    info = MagicMock(language="fr", duration=5.0)
    model.transcribe.side_effect = lambda *args, **kwargs: (
        iter([seg1, seg2]),
        info,
    )
    return model


# ---------------------------------------------------------------------------
# transcribe()
# ---------------------------------------------------------------------------


async def test_transcribe_returns_correct_text(mock_whisper_model, engine):
    # Act
    result = await engine.transcribe(b"fake audio")

    # Assert
    assert isinstance(result, TranscriptionResult)
    assert result.text == "Bonjour tout le monde"


async def test_transcribe_returns_correct_language(mock_whisper_model, engine):
    result = await engine.transcribe(b"fake audio")
    assert result.language == "fr"


async def test_transcribe_returns_correct_duration(mock_whisper_model, engine):
    result = await engine.transcribe(b"fake audio")
    assert result.duration == 5.0


async def test_transcribe_returns_two_segments(mock_whisper_model, engine):
    result = await engine.transcribe(b"fake audio")
    assert len(result.segments) == 2


async def test_transcribe_segment_fields(mock_whisper_model, engine):
    result = await engine.transcribe(b"fake audio")
    first = result.segments[0]

    assert isinstance(first, SegmentResult)
    assert first.index == 0
    assert first.start == 0.0
    assert first.end == 2.5
    assert first.text == " Bonjour"


async def test_transcribe_passes_language_to_model(mock_whisper_model, engine):
    await engine.transcribe(b"fake audio", language="en")

    call_kwargs = mock_whisper_model.transcribe.call_args[1]
    assert call_kwargs["language"] == "en"


async def test_transcribe_passes_prompt_to_model(mock_whisper_model, engine):
    await engine.transcribe(b"fake audio", prompt="hello")

    call_kwargs = mock_whisper_model.transcribe.call_args[1]
    assert call_kwargs["initial_prompt"] == "hello"


async def test_transcribe_acquires_and_releases_semaphore(settings, mock_whisper_model):
    # Arrange
    eng = WhisperEngine(settings)
    eng._model = mock_whisper_model
    initial_value = eng._semaphore._value

    # Act
    await eng.transcribe(b"fake audio")

    # Assert: semaphore was released, value restored
    assert eng._semaphore._value == initial_value


async def test_transcribe_raises_queue_timeout_error(settings, mock_whisper_model):
    # Arrange: set GPU_TIMEOUT to nearly zero so the semaphore times out
    settings_timeout = _make_settings(GPU_TIMEOUT=1, GPU_CONCURRENCY=1)
    eng = WhisperEngine(settings_timeout)
    eng._model = mock_whisper_model
    # Hold the semaphore so the next acquire will time out
    await eng._semaphore.acquire()

    # Act / Assert
    with pytest.raises(QueueTimeoutError):
        await asyncio.wait_for(eng.transcribe(b"fake audio"), timeout=3.0)

    # Cleanup
    eng._semaphore.release()


async def test_transcribe_raises_transcription_error_when_model_not_loaded(settings):
    # Arrange
    eng = WhisperEngine(settings)
    # _model is None by default

    # Act / Assert
    with pytest.raises(TranscriptionError, match="not loaded"):
        await eng.transcribe(b"fake audio")


async def test_transcribe_wraps_model_exception(settings):
    # Arrange
    eng = WhisperEngine(settings)
    bad_model = MagicMock()
    bad_model.transcribe.side_effect = RuntimeError("cuda oom")
    eng._model = bad_model

    # Act / Assert
    with pytest.raises(TranscriptionError, match="cuda oom"):
        await eng.transcribe(b"fake audio")


# ---------------------------------------------------------------------------
# transcribe_stream()
# ---------------------------------------------------------------------------


async def test_transcribe_stream_yields_segments_then_result(
    mock_whisper_model, engine
):
    # Act
    items = []
    async for item in engine.transcribe_stream(b"fake audio"):
        items.append(item)

    # Assert: 2 segments + 1 final TranscriptionResult
    assert len(items) == 3
    assert isinstance(items[0], SegmentResult)
    assert isinstance(items[1], SegmentResult)
    assert isinstance(items[2], TranscriptionResult)


async def test_transcribe_stream_final_result_text(mock_whisper_model, engine):
    items = []
    async for item in engine.transcribe_stream(b"fake audio"):
        items.append(item)

    final = items[-1]
    assert isinstance(final, TranscriptionResult)
    assert final.text == "Bonjour tout le monde"


async def test_transcribe_stream_segment_order(mock_whisper_model, engine):
    segments = []
    async for item in engine.transcribe_stream(b"fake audio"):
        if isinstance(item, SegmentResult):
            segments.append(item)

    assert segments[0].start < segments[1].start


# ---------------------------------------------------------------------------
# unload()
# ---------------------------------------------------------------------------


def test_unload_sets_model_to_none(engine):
    # Arrange: engine has a mock model loaded
    assert engine._model is not None

    # Act
    engine.unload()

    # Assert
    assert engine._model is None
    assert engine.is_loaded is False


# ---------------------------------------------------------------------------
# is_loaded property
# ---------------------------------------------------------------------------


def test_is_loaded_true_when_model_set(engine):
    assert engine.is_loaded is True


def test_is_loaded_false_when_model_none(settings):
    eng = WhisperEngine(settings)
    assert eng.is_loaded is False


# ---------------------------------------------------------------------------
# queue_size property
# ---------------------------------------------------------------------------


async def test_queue_size_zero_when_idle(engine):
    # Arrange / Act / Assert
    assert engine.queue_size == 0


async def test_queue_size_nonzero_when_semaphore_held(settings, mock_whisper_model):
    eng = WhisperEngine(settings)
    eng._model = mock_whisper_model

    await eng._semaphore.acquire()
    try:
        assert eng.queue_size == 1
    finally:
        eng._semaphore.release()
