"""Shared pytest fixtures for the T4lk server test suite."""

from unittest.mock import MagicMock, patch

import httpx
import pytest


def _make_transcribe_return_value():
    """Build a fresh mock return value for model.transcribe().

    Returns a new iterator each call so tests don't consume the same one.
    """
    segment1 = MagicMock(start=0.0, end=2.5, text=" Bonjour")
    segment2 = MagicMock(start=2.5, end=5.0, text=" tout le monde")
    info = MagicMock(language="fr", duration=5.0)
    return iter([segment1, segment2]), info


@pytest.fixture
def mock_whisper_model():
    """Mock of faster_whisper.WhisperModel returning predictable segments."""
    model = MagicMock()
    model.transcribe.side_effect = lambda *args, **kwargs: (
        _make_transcribe_return_value()
    )
    return model


@pytest.fixture
def settings():
    """Settings with DEVICE='cpu' for testing (no GPU required)."""
    from stt.settings import Settings

    return Settings(DEVICE="cpu", GPU_TIMEOUT=5, GPU_CONCURRENCY=1)


@pytest.fixture
def engine(settings, mock_whisper_model):
    """WhisperEngine initialized with test settings and pre-loaded mock model."""
    from stt.engine import WhisperEngine

    eng = WhisperEngine(settings)
    eng._model = mock_whisper_model
    return eng


@pytest.fixture
async def client(engine):
    """httpx.AsyncClient with the FastAPI app mounted and mock engine injected."""
    with patch("stt.engine.WhisperModel"):
        from stt.main import create_app

        app = create_app()
        # Bypass the real lifespan (which would try to load the GPU model)
        # by injecting the pre-loaded mock engine directly.
        app.state.engine = engine
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as c:
            yield c
