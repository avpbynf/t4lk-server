# Testing Guide -- T4lk

## Overview

This guide covers pytest conventions, fixture patterns, and coverage
configuration for the T4lk server (t4lk-server).

## Running Tests

```bash
make test          # run all tests with coverage (80% minimum)
```

Coverage minimum threshold: **80%**.

## conftest.py Conventions

The `conftest.py` file at the package root defines shared fixtures. Scope rules:

- `scope="session"` -- expensive resources (model loading, GPU init)
- `scope="function"` (default) -- state-sensitive resources (uploaded files, mock engine)

```python
# conftest.py
import pytest
from httpx import ASGITransport, AsyncClient
from rest.main import create_app

@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

## Fixture Patterns

### WhisperEngine mock fixture

```python
@pytest.fixture
def mock_engine(mocker):
    engine = mocker.AsyncMock()
    engine.transcribe.return_value = TranscriptionResult(
        text="test transcription",
        language="fr",
        duration=1.0,
        segments=[],
    )
    return engine
```

### Audio file fixture

```python
@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "test.wav"
    # Generate minimal valid WAV
    path.write_bytes(b"RIFF" + b"\x00" * 40)
    return path
```

## Coverage Configuration

Coverage is configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
source = ["rest"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

## Debugging Test Failures

1. Run with `-v` for verbose output: `pytest -v tests/`
2. Run a single test: `pytest tests/test_engine.py::test_transcribe -v`
3. Drop into debugger on failure: `pytest --pdb tests/`
4. Show locals on failure: `pytest -l tests/`
5. Check for async issues: ensure `asyncio_mode = "auto"` in pyproject.toml

## Test Naming Conventions

- Files: `test_<module_name>.py`
- Functions: `test_<what_is_tested>_<condition>_<expected_outcome>`
- Example: `test_create_transcription_invalid_format_returns_400`

## AAA Pattern

All test functions follow Arrange / Act / Assert:

```python
async def test_health_returns_ok(client):
    # Arrange -- nothing needed

    # Act
    response = await client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```
