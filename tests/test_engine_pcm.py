"""Tests for the PCM streaming transcription method."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from rest.engine import SegmentResult, TranscriptionResult, WhisperEngine
from rest.exceptions import QueueTimeoutError
from rest.settings import Settings


@pytest.fixture
def pcm_settings():
    return Settings(DEVICE="cpu", GPU_TIMEOUT=5, GPU_CONCURRENCY=1)


@pytest.fixture
def pcm_engine(pcm_settings):
    engine = WhisperEngine(pcm_settings)
    model = MagicMock()
    seg1 = MagicMock(start=0.0, end=2.5, text=" Bonjour")
    seg2 = MagicMock(start=2.5, end=5.0, text=" tout le monde")
    info = MagicMock(language="fr", duration=5.0)
    model.transcribe.return_value = (iter([seg1, seg2]), info)
    engine._model = model
    return engine


@pytest.mark.asyncio
async def test_transcribe_stream_pcm_yields_segments_then_result(pcm_engine):
    """Segments are yielded one by one, followed by a TranscriptionResult."""
    audio = np.zeros(16000 * 5, dtype=np.float32)
    items = []
    async for item in pcm_engine.transcribe_stream_pcm(audio, "fr", None):
        items.append(item)

    assert len(items) == 3
    assert isinstance(items[0], SegmentResult)
    assert items[0].index == 0
    assert items[0].text == " Bonjour"
    assert isinstance(items[1], SegmentResult)
    assert items[1].index == 1
    assert items[1].text == " tout le monde"
    assert isinstance(items[2], TranscriptionResult)
    assert items[2].text == "Bonjour tout le monde"
    assert items[2].language == "fr"
    assert items[2].duration == 5.0


@pytest.mark.asyncio
async def test_transcribe_stream_pcm_passes_numpy_directly(pcm_engine):
    """The numpy array is passed directly to the model, not wrapped in BytesIO."""
    audio = np.ones(16000, dtype=np.float32)
    async for _ in pcm_engine.transcribe_stream_pcm(audio, "fr", "prompt"):
        pass
    call_args = pcm_engine._model.transcribe.call_args
    assert isinstance(call_args[0][0], np.ndarray)
    assert call_args[1]["initial_prompt"] == "prompt"


@pytest.mark.asyncio
async def test_transcribe_stream_pcm_releases_semaphore_on_error():
    """GPU semaphore is released even if transcription fails."""
    settings = Settings(DEVICE="cpu", GPU_TIMEOUT=5, GPU_CONCURRENCY=1)
    engine = WhisperEngine(settings)
    model = MagicMock()
    model.transcribe.side_effect = RuntimeError("GPU error")
    engine._model = model
    audio = np.zeros(16000, dtype=np.float32)

    with pytest.raises(Exception, match="GPU error"):
        async for _ in engine.transcribe_stream_pcm(audio, None, None):
            pass

    assert engine._semaphore._value == 1


@pytest.mark.asyncio
async def test_transcribe_stream_pcm_queue_timeout():
    """QueueTimeoutError raised when GPU is busy beyond timeout."""
    settings = Settings(DEVICE="cpu", GPU_TIMEOUT=0, GPU_CONCURRENCY=1)
    engine = WhisperEngine(settings)
    engine._model = MagicMock()
    await engine._semaphore.acquire()

    audio = np.zeros(16000, dtype=np.float32)
    with pytest.raises(QueueTimeoutError):
        async for _ in engine.transcribe_stream_pcm(audio, None, None):
            pass

    engine._semaphore.release()
