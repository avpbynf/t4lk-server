"""Shared pytest fixtures for the Talk server test suite."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def _make_transcribe_return_value():
    """Build a fresh mock return value for model.transcribe()."""
    segment1 = MagicMock(start=0.0, end=2.5, text=" Bonjour")
    segment2 = MagicMock(start=2.5, end=5.0, text=" tout le monde")
    info = MagicMock(language="fr", duration=5.0)
    return iter([segment1, segment2]), info


@pytest.fixture
def mock_whisper_model():
    """Mock of faster_whisper.WhisperModel returning predictable segments."""
    model = MagicMock()
    model.transcribe.side_effect = lambda *a, **k: _make_transcribe_return_value()
    return model


@pytest.fixture
def settings():
    """Settings with DEVICE='cpu' for testing (no GPU required)."""
    from rest.settings import Settings

    return Settings(DEVICE="cpu", GPU_TIMEOUT=5, GPU_CONCURRENCY=1)


@pytest.fixture
def engine(settings, mock_whisper_model):
    """WhisperEngine with a pre-loaded mock model."""
    from rest.engine import WhisperEngine

    eng = WhisperEngine(settings)
    eng._model = mock_whisper_model
    return eng


@pytest.fixture
async def db_session_maker():
    """Real in-memory SQLite (shared connection via StaticPool), tables created."""
    from rest.db.models import Base

    db_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(db_engine, expire_on_commit=False)
    await db_engine.dispose()


@pytest.fixture
async def auth_token(db_session_maker):
    """Mint a real token in the test DB and return its plain value."""
    from rest.auth.tokens import create_token

    async with db_session_maker() as session:
        _, plain = await create_token(session, "test")
        await session.commit()
    return plain


@pytest.fixture
def app_factory(engine, db_session_maker, monkeypatch):
    """Build the app with the mock engine, test DB, and ADMIN_TOKEN configured."""
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")

    def _build():
        with patch("rest.engine.WhisperModel"):
            from rest.db.database import get_db
            from rest.main import create_app
            from rest.settings import get_settings

            get_settings.cache_clear()
            app = create_app()
            app.state.engine = engine

            async def _override_get_db():
                async with db_session_maker() as session:
                    try:
                        yield session
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise

            app.dependency_overrides[get_db] = _override_get_db
            return app

    return _build


@pytest.fixture
async def client(app_factory, auth_token):
    """AsyncClient that sends a valid Bearer token (authenticated by default)."""
    app = app_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": f"Bearer {auth_token}"},
    ) as c:
        yield c


@pytest.fixture
async def unauth_client(app_factory):
    """AsyncClient with no Authorization header (for 401 tests)."""
    app = app_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        yield c
