# Whisper-only REST + Token Auth (SQLite + admin) — Implementation Plan

> **For agentic workers:** Execute this plan task-by-task using `/execute`.
> Steps use checkbox (`- [ ]`) syntax for tracking.
> Source spec: `docs/decisions/2026-06-01-whisper-rest-token-auth-design.md`.
> Implementation branch: `feature/whisper-rest-token-auth` (already created from `main`).

**Goal:** Turn the server into a Whisper-only OpenAI-compatible REST API (drop the WebSocket) and restore the
DB-backed Bearer token auth + admin panel that was stripped in commit `7c447cd`, ported into the `rest/` package on SQLite.

**Architecture:** Start from `main` (already faster-whisper + light CUDA image). Phase A removes the WebSocket.
Phase B recovers `auth/` + `db/` + `admin/` from commit `bb42967`, adapts them to the `rest/` package and
`pydantic-settings`, backs them with SQLite (aiosqlite), protects `/v1` routes with a `verify_token` dependency,
adds a `UsageLogMiddleware` to make usage stats real, and serves the admin dashboard under `/admin`.

**Tech Stack:** FastAPI, faster-whisper, SQLAlchemy 2.0 async, aiosqlite, pytest + pytest-asyncio + httpx.

**Conventions:** Code/docstrings in English (Google style). `make test` (pytest, ≥80% coverage) and `make lint`
(ruff + mypy) must pass. Recover old code with `git show bb42967:<path>`. Commit after each task.

---

## Dependency graph & ordering

```
Phase A (WebSocket removal) — independent, do first:
  A1 (remove WS files + main wiring)
  A2 (remove transcribe_stream_pcm)
  A3 (remove WS settings)
  → after A1-A3: `make test` green (WS tests deleted)

Phase B (auth/db/admin restore):
  B1 (deps + settings)
   └── B2 (db layer)
        └── B3 (auth tokens)
             └── B4 (verify_token dependency + conftest)   ← edits conftest.py
                  └── B5 (wire auth into main.py)           ┐
                       └── B6 (UsageLogMiddleware)          │ all edit rest/main.py
                            └── B7 (admin routes + panel)   ┘ → SEQUENTIAL, not parallel
  B8 (docker-compose volume + .gitignore) — after B1, independent of B2-B7
  B9 (docs: CLAUDE.md) — last, after everything
```

**Shared-file warning:** Tasks **A1, B5, B6, B7 all edit `rest/main.py`** and **B4, B5 edit `tests/conftest.py`**.
These must run **sequentially in the order above** (no parallel worktrees on the same file).

---

# PHASE A — Whisper-only REST (remove WebSocket)

These are deletion tasks. There is no new behavior to test-drive; verification is that the **existing suite stays
green after the matching WS tests are deleted**.

### Task A1: Remove WebSocket files and wiring

**Files:**
- Delete: `rest/v1/transcriptions/ws_handler.py`
- Delete: `rest/v1/transcriptions/ws_models.py`
- Delete: `rest/v1/transcriptions/ws_router.py`
- Delete: `tests/test_ws_handler.py`
- Delete: `tests/test_ws_integration.py`
- Modify: `rest/main.py`

- [ ] **Step 1: Delete the WS source and test files**

```bash
cd t4lk-server
git rm rest/v1/transcriptions/ws_handler.py \
       rest/v1/transcriptions/ws_models.py \
       rest/v1/transcriptions/ws_router.py \
       tests/test_ws_handler.py \
       tests/test_ws_integration.py
```

- [ ] **Step 2: Remove the ws_router import and include from `rest/main.py`**

Delete this import line (currently line 19):

```python
from rest.v1.transcriptions.ws_router import ws_router
```

Delete the include in `create_app()` (the line after `app.include_router(router)`):

```python
    app.include_router(ws_router)
```

The block must become just:

```python
    # Routes
    app.include_router(router)
```

- [ ] **Step 3: Run the suite to verify nothing else references the WS**

Run: `cd t4lk-server && uv run pytest -q`
Expected: PASS. No import errors. (`test_engine_pcm.py` still exists and passes until Task A2.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(server): remove WebSocket realtime transcription"
```

---

### Task A2: Remove the WS-only PCM streaming method from the engine

**Files:**
- Modify: `rest/engine.py`
- Delete: `tests/test_engine_pcm.py`

- [ ] **Step 1: Delete the PCM streaming test**

```bash
cd t4lk-server && git rm tests/test_engine_pcm.py
```

- [ ] **Step 2: Remove `transcribe_stream_pcm` from `rest/engine.py`**

Delete the entire `async def transcribe_stream_pcm(...)` method (currently lines 293-396, the last method of
`WhisperEngine`). Keep `transcribe` and `transcribe_stream` (used by REST).

- [ ] **Step 3: Remove the now-unused numpy import**

In `rest/engine.py`, delete the line:

```python
import numpy as np
```

(`np` is only referenced by the removed method. `transcribe`/`transcribe_stream` take `bytes`.)

- [ ] **Step 4: Verify no remaining numpy usage in the engine**

Run: `cd t4lk-server && grep -n "np\.\|numpy" rest/engine.py`
Expected: no output (empty).

- [ ] **Step 5: Run lint + tests**

Run: `cd t4lk-server && uv run ruff check rest/engine.py && uv run pytest -q`
Expected: ruff clean (no unused-import error), tests PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(server): drop WS-only transcribe_stream_pcm from engine"
```

---

### Task A3: Remove WebSocket settings

**Files:**
- Modify: `rest/settings.py`

- [ ] **Step 1: Delete the three WS settings**

In `rest/settings.py`, remove these lines from the `Settings` class:

```python
    WS_MAX_CONNECTIONS: int = 100
    WS_MAX_AUDIO_DURATION: int = 600
    WS_CHUNK_TIMEOUT: int = 30
```

- [ ] **Step 2: Verify nothing references the removed settings**

Run: `cd t4lk-server && grep -rn "WS_MAX_CONNECTIONS\|WS_MAX_AUDIO_DURATION\|WS_CHUNK_TIMEOUT" rest/ tests/`
Expected: no output.

- [ ] **Step 3: Run the full suite with coverage**

Run: `cd t4lk-server && make test`
Expected: PASS, coverage ≥ 80%.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(server): remove WebSocket settings"
```

---

# PHASE B — Restore DB-backed token auth + admin (SQLite)

### Task B1: Add dependencies and settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `rest/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Add runtime dependencies**

In `pyproject.toml`, add to `dependencies` (after `pydantic-settings`):

```toml
    "sqlalchemy[asyncio]>=2.0.0",
    "aiosqlite>=0.20.0",
```

- [ ] **Step 2: Add auth/db settings**

In `rest/settings.py`, add these fields to the `Settings` class (after `DEFAULT_LANGUAGE`):

```python
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/tokens.db"
    ADMIN_TOKEN: str = ""
```

- [ ] **Step 3: Document the new env vars in `.env.example`**

Append to `.env.example`:

```env

# Token database (SQLite file; lives in the persistent `token-data` volume)
DATABASE_URL=sqlite+aiosqlite:///./data/tokens.db

# Admin token for managing API tokens via /admin endpoints (empty = admin disabled)
# Generate with: make token
ADMIN_TOKEN=
```

- [ ] **Step 4: Sync the lock file**

Run: `cd t4lk-server && uv sync`
Expected: `sqlalchemy` and `aiosqlite` installed, `uv.lock` updated.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock rest/settings.py .env.example
git commit -m "feat(server): add sqlalchemy/aiosqlite deps and auth settings"
```

---

### Task B2: Database layer (SQLite, SQLAlchemy 2.0 async)

**Files:**
- Create: `rest/db/__init__.py`
- Create: `rest/db/models.py`
- Create: `rest/db/database.py`
- Test: `tests/test_db.py`

> Cohesive component (one package + its test). Recovered/adapted from `bb42967:db/`. Postgres → SQLite,
> `os.getenv` → `rest.settings`, UUID via explicit `Uuid` type, WAL + FK pragmas, `init_db` creates the data dir.

- [ ] **Step 1: Write the failing test** — `tests/test_db.py`

```python
"""Tests for the token database layer (real in-memory SQLite)."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from rest.db.models import Base, Token, UsageLog


@pytest.fixture
async def session_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_token_uuid_roundtrip(session_maker):
    async with session_maker() as s:
        token = Token(key_hash="abc", name="laptop")
        s.add(token)
        await s.commit()
        await s.refresh(token)
        token_id = token.id

    async with session_maker() as s:
        from sqlalchemy import select

        fetched = (await s.execute(select(Token).where(Token.id == token_id))).scalar_one()
        assert fetched.name == "laptop"
        assert fetched.is_active is True
        assert fetched.usage_count == 0
        assert str(fetched.id) == str(token_id)


async def test_usage_log_fk_relationship(session_maker):
    async with session_maker() as s:
        token = Token(key_hash="h", name="t")
        s.add(token)
        await s.flush()
        s.add(UsageLog(token_id=token.id, endpoint="/v1/audio/transcriptions", process_time=1.2))
        await s.commit()
        await s.refresh(token, attribute_names=["usage_logs"])
        assert len(token.usage_logs) == 1
        assert token.usage_logs[0].endpoint == "/v1/audio/transcriptions"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd t4lk-server && uv run pytest tests/test_db.py -q`
Expected: FAIL — `rest.db` does not exist.

- [ ] **Step 3: Create `rest/db/models.py`**

```python
"""SQLAlchemy 2.0 models for the token database."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (for SQLite storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class Token(Base):
    """An API token, stored as a SHA256 hash (the plain token is shown once)."""

    __tablename__ = "tokens"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    usage_logs: Mapped[list["UsageLog"]] = relationship(
        "UsageLog", back_populates="token", cascade="all, delete-orphan"
    )


class UsageLog(Base):
    """One row per authenticated request, used for usage statistics."""

    __tablename__ = "usage_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    token_id: Mapped[UUID] = mapped_column(ForeignKey("tokens.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    process_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    token: Mapped["Token"] = relationship("Token", back_populates="usage_logs")
```

- [ ] **Step 4: Create `rest/db/database.py`**

```python
"""Async SQLite database connection (SQLAlchemy 2.0)."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from rest.db.models import Base
from rest.settings import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    """Enable WAL journaling and foreign-key enforcement per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session, committing on success."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create the data directory (if any) and all tables. Idempotent."""
    url = _settings.DATABASE_URL
    if url.startswith("sqlite") and "///" in url:
        path = url.split("///", 1)[1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose of the engine connection pool. Call on shutdown."""
    await engine.dispose()
```

- [ ] **Step 5: Create `rest/db/__init__.py`**

```python
"""Token database layer (SQLite via SQLAlchemy async)."""

from rest.db.database import (
    async_session_maker,
    close_db,
    engine,
    get_db,
    init_db,
)
from rest.db.models import Base, Token, UsageLog

__all__ = [
    "engine",
    "async_session_maker",
    "get_db",
    "init_db",
    "close_db",
    "Base",
    "Token",
    "UsageLog",
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd t4lk-server && uv run pytest tests/test_db.py -q`
Expected: PASS (UUID roundtrip + FK relationship work on SQLite).

- [ ] **Step 7: Commit**

```bash
git add rest/db/ tests/test_db.py
git commit -m "feat(server): add SQLite token database layer"
```

---

### Task B3: Token generation, hashing, and CRUD

**Files:**
- Create: `rest/auth/__init__.py`
- Create: `rest/auth/tokens.py`
- Test: `tests/test_tokens.py`

> Adapted from `bb42967:auth/tokens.py`. **Improvement:** `get_token_by_plain` does an O(1) indexed lookup
> by `key_hash` (the SHA256 hash is deterministic) instead of iterating all active tokens.

- [ ] **Step 1: Write the failing test** — `tests/test_tokens.py`

```python
"""Tests for token generation, hashing, and CRUD."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from rest.auth.tokens import (
    create_token,
    generate_token,
    get_token_by_plain,
    hash_token,
    list_tokens,
    revoke_token,
    update_token_usage,
    verify_token_hash,
)
from rest.db.models import Base


@pytest.fixture
async def session_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def test_generate_token_has_prefix_and_hash():
    plain, hashed = generate_token()
    assert plain.startswith("sk_")
    assert len(hashed) == 64
    assert hash_token(plain) == hashed


def test_verify_token_hash_constant_time():
    plain, hashed = generate_token()
    assert verify_token_hash(plain, hashed) is True
    assert verify_token_hash("sk_wrong", hashed) is False


async def test_create_and_lookup_token(session_maker):
    async with session_maker() as s:
        token, plain = await create_token(s, "laptop")
        await s.commit()
    async with session_maker() as s:
        found = await get_token_by_plain(s, plain)
        assert found is not None
        assert found.name == "laptop"


async def test_revoked_token_not_returned(session_maker):
    async with session_maker() as s:
        token, plain = await create_token(s, "old")
        await s.commit()
        token_id = token.id
    async with session_maker() as s:
        assert await revoke_token(s, token_id) is True
        await s.commit()
    async with session_maker() as s:
        assert await get_token_by_plain(s, plain) is None


async def test_update_token_usage_increments(session_maker):
    async with session_maker() as s:
        token, _ = await create_token(s, "t")
        await s.commit()
        await update_token_usage(s, token)
        await s.commit()
        assert token.usage_count == 1
        assert token.last_used_at is not None


async def test_list_tokens_excludes_inactive_by_default(session_maker):
    async with session_maker() as s:
        t1, _ = await create_token(s, "active")
        t2, _ = await create_token(s, "revoked")
        await s.commit()
        await revoke_token(s, t2.id)
        await s.commit()
        active = await list_tokens(s)
        assert [t.name for t in active] == ["active"]
        all_tokens = await list_tokens(s, include_inactive=True)
        assert len(all_tokens) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd t4lk-server && uv run pytest tests/test_tokens.py -q`
Expected: FAIL — `rest.auth.tokens` does not exist.

- [ ] **Step 3: Create `rest/auth/tokens.py`**

```python
"""Token generation, hashing, and CRUD operations."""

import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rest.db.models import Token, UsageLog, utcnow

TOKEN_PREFIX = "sk_"
TOKEN_BYTES = 16  # 32 hex characters


def generate_token() -> tuple[str, str]:
    """Generate a new token. Returns (plain "sk_…", sha256_hex_hash)."""
    plain = f"{TOKEN_PREFIX}{secrets.token_hex(TOKEN_BYTES)}"
    return plain, hash_token(plain)


def hash_token(token: str) -> str:
    """Return the SHA256 hex digest of a token."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token_hash(plain: str, hashed: str) -> bool:
    """Constant-time comparison of a plain token against a stored hash."""
    return secrets.compare_digest(hash_token(plain), hashed)


async def create_token(db: AsyncSession, name: str) -> tuple[Token, str]:
    """Create and persist a token. Returns (model, plain) — plain is shown once."""
    plain, hashed = generate_token()
    token = Token(key_hash=hashed, name=name)
    db.add(token)
    await db.flush()
    await db.refresh(token)
    return token, plain


async def get_token_by_plain(db: AsyncSession, plain_token: str) -> Token | None:
    """Return the active token matching a plain value via an indexed hash lookup."""
    hashed = hash_token(plain_token)
    result = await db.execute(
        select(Token).where(Token.key_hash == hashed, Token.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_token_by_id(db: AsyncSession, token_id: UUID) -> Token | None:
    """Return a token by id, or None."""
    result = await db.execute(select(Token).where(Token.id == token_id))
    return result.scalar_one_or_none()


async def list_tokens(db: AsyncSession, include_inactive: bool = False) -> list[Token]:
    """Return tokens (newest first); active-only unless include_inactive is True."""
    stmt = select(Token).order_by(Token.created_at.desc())
    if not include_inactive:
        stmt = stmt.where(Token.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def revoke_token(db: AsyncSession, token_id: UUID) -> bool:
    """Soft-delete a token (is_active=False). Returns True if it existed."""
    token = await get_token_by_id(db, token_id)
    if token is None:
        return False
    token.is_active = False
    await db.flush()
    return True


async def update_token_usage(db: AsyncSession, token: Token) -> None:
    """Increment usage_count and set last_used_at to now."""
    token.usage_count += 1
    token.last_used_at = utcnow()
    await db.flush()


async def get_token_stats(db: AsyncSession, token_id: UUID) -> dict | None:
    """Return aggregated usage statistics for a token, or None if not found."""
    result = await db.execute(
        select(Token)
        .where(Token.id == token_id)
        .options(selectinload(Token.usage_logs))
    )
    token = result.scalar_one_or_none()
    if token is None:
        return None

    logs: list[UsageLog] = list(token.usage_logs)
    endpoint_breakdown: dict[str, int] = {}
    total_pt = 0.0
    pt_count = 0
    for log in logs:
        endpoint_breakdown[log.endpoint] = endpoint_breakdown.get(log.endpoint, 0) + 1
        if log.process_time is not None:
            total_pt += log.process_time
            pt_count += 1
    avg_pt = round(total_pt / pt_count, 3) if pt_count else None
    recent = sorted(logs, key=lambda x: x.timestamp, reverse=True)[:10]

    return {
        "token_id": str(token.id),
        "token_name": token.name,
        "total_requests": len(logs),
        "usage_count": token.usage_count,
        "endpoint_breakdown": endpoint_breakdown,
        "average_process_time": avg_pt,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "recent_logs": [
            {
                "id": str(log.id),
                "endpoint": log.endpoint,
                "timestamp": log.timestamp.isoformat(),
                "process_time": log.process_time,
            }
            for log in recent
        ],
    }
```

- [ ] **Step 4: Create `rest/auth/__init__.py`** (dependencies added in Task B4)

```python
"""Token-based authentication."""

from rest.auth.tokens import (
    create_token,
    generate_token,
    get_token_by_id,
    get_token_by_plain,
    get_token_stats,
    hash_token,
    list_tokens,
    revoke_token,
    update_token_usage,
    verify_token_hash,
)

__all__ = [
    "create_token",
    "generate_token",
    "get_token_by_id",
    "get_token_by_plain",
    "get_token_stats",
    "hash_token",
    "list_tokens",
    "revoke_token",
    "update_token_usage",
    "verify_token_hash",
]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd t4lk-server && uv run pytest tests/test_tokens.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add rest/auth/__init__.py rest/auth/tokens.py tests/test_tokens.py
git commit -m "feat(server): add token generation, hashing, and CRUD"
```

---

### Task B4: `verify_token` dependency + test harness

**Files:**
- Create: `rest/auth/dependencies.py`
- Modify: `rest/auth/__init__.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_auth.py`

> `HTTPBearer(auto_error=False)` so a **missing** header yields 401 (not 403). Sets `request.state.token_id`
> for `UsageLogMiddleware` (Task B6). The conftest gains a real in-memory SQLite + a minted token, and the
> existing `client` fixture sends `Authorization: Bearer <token>` so prior transcription tests keep passing.

- [ ] **Step 1: Create `rest/auth/dependencies.py`**

```python
"""FastAPI auth dependency: Bearer token verification against the database."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from rest.auth.tokens import get_token_by_plain, update_token_usage
from rest.db.database import get_db
from rest.db.models import Token

security = HTTPBearer(auto_error=False)


async def verify_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Verify the Bearer token, record usage, and expose token_id for logging.

    Raises:
        HTTPException: 401 if the header is missing, or the token is unknown/revoked.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = await get_token_by_plain(db, credentials.credentials)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await update_token_usage(db, token)
    request.state.token_id = token.id
    return token


CurrentToken = Annotated[Token, Depends(verify_token)]
```

- [ ] **Step 2: Export the dependency from `rest/auth/__init__.py`**

Add to the imports and `__all__` in `rest/auth/__init__.py`:

```python
from rest.auth.dependencies import CurrentToken, verify_token
```

Add `"verify_token"` and `"CurrentToken"` to `__all__`.

- [ ] **Step 3: Rewrite `tests/conftest.py`** to add a real test DB + authed/unauthed clients

```python
"""Shared pytest fixtures for the T4lk server test suite."""

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
            app.state.db_sessionmaker = db_session_maker

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
```

- [ ] **Step 4: Write `tests/test_auth.py`**

```python
"""Integration tests for Bearer token auth on /v1 routes."""

_WAV = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00"
    b"\x02\x00\x10\x00data\x00\x00\x00\x00"
)


def _audio():
    return {"file": ("t.wav", _WAV, "audio/wav")}


async def test_health_is_public(unauth_client):
    assert (await unauth_client.get("/health")).status_code == 200


async def test_transcription_without_token_returns_401(unauth_client):
    r = await unauth_client.post("/v1/audio/transcriptions", files=_audio())
    assert r.status_code == 401


async def test_transcription_with_bad_token_returns_401(app_factory):
    import httpx

    app = app_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": "Bearer sk_invalid"},
    ) as c:
        r = await c.post("/v1/audio/transcriptions", files=_audio())
    assert r.status_code == 401


async def test_transcription_with_valid_token_returns_200(client):
    r = await client.post("/v1/audio/transcriptions", files=_audio())
    assert r.status_code == 200
```

- [ ] **Step 5: Run the auth tests — they fail until wiring (Task B5)**

Run: `cd t4lk-server && uv run pytest tests/test_auth.py -q`
Expected: `test_health_is_public` PASS; the 401/200 tests **FAIL** (routes not yet protected). This is expected —
Task B5 wires `verify_token` onto the router and turns these green.

- [ ] **Step 6: Commit**

```bash
git add rest/auth/ tests/conftest.py tests/test_auth.py
git commit -m "feat(server): add verify_token dependency and auth test harness"
```

---

### Task B5: Protect `/v1` routes and wire DB lifecycle into the app

**Files:**
- Modify: `rest/main.py`

> Sequential after B4 (shares `rest/main.py` with B6/B7). Adds `init_db`/`close_db` to the lifespan, exposes the
> session maker on `app.state` (for the middleware in B6), and attaches `Depends(verify_token)` to the `/v1` router.

- [ ] **Step 1: Update the lifespan and imports in `rest/main.py`**

Add imports near the top:

```python
from fastapi import Depends
from rest.auth.dependencies import verify_token
from rest.db.database import async_session_maker, close_db, init_db
```

Replace the `lifespan` body so it initialises the DB and exposes the session maker:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    await init_db()
    app.state.db_sessionmaker = async_session_maker

    engine = WhisperEngine(settings)
    await engine.load()
    app.state.engine = engine

    yield

    engine.unload()
    await close_db()
```

- [ ] **Step 2: Attach `verify_token` to the `/v1` router include**

In `create_app()`, change the route include from:

```python
    # Routes
    app.include_router(router)
```

to:

```python
    # Routes — all /v1 endpoints require a valid Bearer token
    app.include_router(router, dependencies=[Depends(verify_token)])
```

`/health` is registered separately (below) and stays public.

- [ ] **Step 3: Run the auth tests to verify they now pass**

Run: `cd t4lk-server && uv run pytest tests/test_auth.py -q`
Expected: PASS (401 without/with bad token, 200 with valid token).

- [ ] **Step 4: Run the full suite (existing transcription tests now authed via conftest)**

Run: `cd t4lk-server && uv run pytest -q`
Expected: PASS. The existing `tests/test_transcriptions.py` pass because the `client` fixture sends a valid token.

- [ ] **Step 5: Commit**

```bash
git add rest/main.py
git commit -m "feat(server): require Bearer token on /v1, init token DB on startup"
```

---

### Task B6: UsageLogMiddleware (make stats real)

**Files:**
- Modify: `rest/middlewares.py`
- Modify: `rest/main.py`
- Test: `tests/test_usage_log.py`

> Fixes the latent gap: the original code never wrote `UsageLog` rows. The middleware reads `request.state.token_id`
> (set by `verify_token`) and the session maker from `request.app.state.db_sessionmaker` (so tests use the test DB).

- [ ] **Step 1: Write the failing test** — `tests/test_usage_log.py`

```python
"""Test that authenticated requests write UsageLog rows."""

from sqlalchemy import func, select

from rest.db.models import UsageLog

_WAV = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00"
    b"\x02\x00\x10\x00data\x00\x00\x00\x00"
)


async def test_authenticated_request_writes_usage_log(client, db_session_maker):
    await client.post("/v1/audio/transcriptions", files={"file": ("t.wav", _WAV, "audio/wav")})

    async with db_session_maker() as s:
        count = (await s.execute(select(func.count()).select_from(UsageLog))).scalar_one()
        row = (await s.execute(select(UsageLog))).scalars().first()

    assert count == 1
    assert row.endpoint == "/v1/audio/transcriptions"
    assert row.process_time is not None


async def test_public_health_writes_no_usage_log(client, db_session_maker):
    await client.get("/health")
    async with db_session_maker() as s:
        count = (await s.execute(select(func.count()).select_from(UsageLog))).scalar_one()
    assert count == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd t4lk-server && uv run pytest tests/test_usage_log.py -q`
Expected: FAIL — no `UsageLog` rows written (count == 0 for the authed request).

- [ ] **Step 3: Add `UsageLogMiddleware` to `rest/middlewares.py`**

Add this class (after `AccessLogMiddleware`):

```python
class UsageLogMiddleware(BaseHTTPMiddleware):
    """Persist one UsageLog row per request that passed token authentication.

    Reads request.state.token_id (set by verify_token) and the session maker
    exposed on app.state.db_sessionmaker. Failures are logged, never raised.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response = cast(Response, await call_next(request))

        token_id = getattr(request.state, "token_id", None)
        maker = getattr(request.app.state, "db_sessionmaker", None)
        if token_id is not None and maker is not None:
            from rest.db.models import UsageLog

            elapsed = time.perf_counter() - start
            try:
                async with maker() as session:
                    session.add(
                        UsageLog(
                            token_id=token_id,
                            endpoint=request.url.path,
                            process_time=round(elapsed, 4),
                        )
                    )
                    await session.commit()
            except Exception:
                logger.warning("Failed to write usage log", exc_info=True)
        return response
```

- [ ] **Step 4: Register the middleware in `rest/main.py`**

Add `UsageLogMiddleware` to the import from `rest.middlewares`, then register it in `create_app()` after
`AccessLogMiddleware` (so it runs within the access log):

```python
    # 2b. Usage log (writes UsageLog for authenticated requests)
    app.add_middleware(UsageLogMiddleware)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd t4lk-server && uv run pytest tests/test_usage_log.py -q`
Expected: PASS (one UsageLog row for the authed transcription, none for /health).

- [ ] **Step 6: Commit**

```bash
git add rest/middlewares.py rest/main.py tests/test_usage_log.py
git commit -m "feat(server): write usage logs for authenticated requests"
```

---

### Task B7: Admin token management API + dashboard

**Files:**
- Create: `rest/admin/__init__.py`
- Create: `rest/admin/routes.py`
- Create: `rest/admin/static/index.html`
- Modify: `rest/main.py`
- Test: `tests/test_admin.py`

> Adapted from `bb42967:admin/`. `verify_admin_token` reads `settings.ADMIN_TOKEN` and uses
> `secrets.compare_digest` (the original used `!=`). The HTML dashboard is recovered verbatim (it already targets
> the `/admin/tokens` API restored here).

- [ ] **Step 1: Write the failing test** — `tests/test_admin.py`

```python
"""Tests for the admin token-management API."""

import httpx
import pytest

_ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
async def admin_client(app_factory):
    app = app_factory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        yield c


async def test_create_token_requires_admin(admin_client):
    r = await admin_client.post("/admin/tokens", json={"name": "x"})
    assert r.status_code == 401


async def test_create_token_returns_plain_once(admin_client):
    r = await admin_client.post("/admin/tokens", json={"name": "laptop"}, headers=_ADMIN)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "laptop"
    assert body["token"].startswith("sk_")


async def test_list_and_revoke_token(admin_client):
    created = (
        await admin_client.post("/admin/tokens", json={"name": "a"}, headers=_ADMIN)
    ).json()
    token_id = created["id"]

    listed = (await admin_client.get("/admin/tokens", headers=_ADMIN)).json()
    assert any(t["id"] == token_id for t in listed["tokens"])

    deleted = await admin_client.delete(f"/admin/tokens/{token_id}", headers=_ADMIN)
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True


async def test_dashboard_served(admin_client):
    r = await admin_client.get("/admin/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd t4lk-server && uv run pytest tests/test_admin.py -q`
Expected: FAIL — `/admin` routes do not exist (404).

- [ ] **Step 3: Create `rest/admin/routes.py`**

```python
"""Admin API routes for managing API tokens (protected by ADMIN_TOKEN)."""

import secrets
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from rest.auth.tokens import (
    create_token,
    get_token_by_id,
    get_token_stats,
    list_tokens,
    revoke_token,
)
from rest.db.database import get_db
from rest.settings import get_settings


class TokenCreate(BaseModel):
    """Request body for creating a token."""

    name: str


class TokenResponse(BaseModel):
    """Token info without the secret value."""

    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool
    usage_count: int

    model_config = {"from_attributes": True}


class TokenCreatedResponse(TokenResponse):
    """Token info returned once at creation, including the plain token."""

    token: str


class TokenListResponse(BaseModel):
    """List of tokens."""

    tokens: list[TokenResponse]


class TokenStatsResponse(BaseModel):
    """Usage statistics for a token."""

    token_id: str
    token_name: str
    total_requests: int
    usage_count: int
    endpoint_breakdown: dict[str, int]
    average_process_time: float | None
    last_used_at: str | None
    recent_logs: list[dict]


class SuccessResponse(BaseModel):
    """Generic success body."""

    success: bool


admin_security = HTTPBearer(auto_error=False)


async def verify_admin_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(admin_security)],
) -> str:
    """Verify the admin Bearer token against settings.ADMIN_TOKEN (constant-time)."""
    admin_token = get_settings().ADMIN_TOKEN
    if not admin_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_TOKEN not configured",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, admin_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


AdminAuth = Annotated[str, Depends(verify_admin_token)]

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/", response_class=FileResponse)
async def admin_dashboard() -> FileResponse:
    """Serve the admin dashboard HTML page."""
    return FileResponse(
        Path(__file__).parent / "static" / "index.html", media_type="text/html"
    )


@router.post(
    "/tokens", response_model=TokenCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def create_new_token(
    body: TokenCreate,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenCreatedResponse:
    """Create a token. The plain token is only returned here, once."""
    token, plain = await create_token(db, body.name)
    return TokenCreatedResponse(
        id=token.id,
        name=token.name,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        is_active=token.is_active,
        usage_count=token.usage_count,
        token=plain,
    )


@router.get("/tokens", response_model=TokenListResponse)
async def list_all_tokens(
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = False,
) -> TokenListResponse:
    """List tokens (active-only unless include_inactive=true)."""
    tokens = await list_tokens(db, include_inactive=include_inactive)
    return TokenListResponse(
        tokens=[TokenResponse.model_validate(t) for t in tokens]
    )


@router.get("/tokens/{token_id}", response_model=TokenResponse)
async def get_token(
    token_id: UUID,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Return a single token's metadata."""
    token = await get_token_by_id(db, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return TokenResponse.model_validate(token)


@router.delete("/tokens/{token_id}", response_model=SuccessResponse)
async def delete_token(
    token_id: UUID,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SuccessResponse:
    """Revoke (soft-delete) a token."""
    if not await revoke_token(db, token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return SuccessResponse(success=True)


@router.get("/tokens/{token_id}/stats", response_model=TokenStatsResponse)
async def get_token_statistics(
    token_id: UUID,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenStatsResponse:
    """Return usage statistics for a token."""
    stats = await get_token_stats(db, token_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return TokenStatsResponse(**stats)
```

- [ ] **Step 4: Create `rest/admin/__init__.py`**

```python
"""Admin module — token management endpoints and dashboard."""

from rest.admin.routes import router

__all__ = ["router"]
```

- [ ] **Step 5: Recover the dashboard HTML**

```bash
cd t4lk-server
mkdir -p rest/admin/static
git show bb42967:admin/static/index.html > rest/admin/static/index.html
```

Verify the dashboard calls the restored API (paths `/admin/tokens`, `/admin/tokens/{id}`, `/admin/tokens/{id}/stats`):

```bash
grep -nE "/admin/tokens|fetch\(|Authorization|Bearer" rest/admin/static/index.html | head
```

Expected: references to `/admin/tokens` and a Bearer/Authorization header input. If the paths differ from the
restored router, adjust the HTML's fetch URLs to match. No backend change.

- [ ] **Step 6: Register the admin router in `rest/main.py`**

Add the import:

```python
from rest.admin import router as admin_router
```

In `create_app()`, after `app.include_router(router, dependencies=[Depends(verify_token)])`, add:

```python
    # Admin token management (protected by its own ADMIN_TOKEN)
    app.include_router(admin_router)
```

- [ ] **Step 7: Run the admin tests to verify they pass**

Run: `cd t4lk-server && uv run pytest tests/test_admin.py -q`
Expected: PASS (401 without admin token, 201 create, list/revoke, dashboard served).

- [ ] **Step 8: Commit**

```bash
git add rest/admin/ rest/main.py tests/test_admin.py
git commit -m "feat(server): restore admin token management API and dashboard"
```

---

### Task B8: Persistent token volume + gitignore

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`

> The token DB must survive `make clean` (`down -v`), so it lives in a dedicated `token-data` volume, not the
> disposable `model-cache`. The Dockerfile already does `COPY rest/ ./rest/`, so the new `rest/{db,auth,admin}`
> packages and `rest/admin/static/` ship automatically — no Dockerfile change.

- [ ] **Step 1: Add the `token-data` volume and DATABASE_URL to `docker-compose.yml`**

Under `services.stt.volumes`, add:

```yaml
      - token-data:/app/data
```

Under `services.stt.environment` (add the key if absent):

```yaml
    environment:
      - DATABASE_URL=sqlite+aiosqlite:////app/data/tokens.db
```

> Note the **four** slashes: `sqlite+aiosqlite:////app/data/tokens.db` is the absolute path `/app/data/tokens.db`.

At the bottom, add to the `volumes:` section:

```yaml
volumes:
  model-cache:
  token-data:
```

- [ ] **Step 2: Ignore the local dev DB directory**

Append to `.gitignore`:

```gitignore
# Local token database (dev)
/data/
```

- [ ] **Step 3: Verify compose config parses**

Run: `cd t4lk-server && docker compose config >/dev/null && echo OK`
Expected: `OK` (valid compose file).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "chore(server): persist token DB in a dedicated volume"
```

---

### Task B9: Update project documentation

**Files:**
- Modify: `../CLAUDE.md` (parent repo — commit separately there)

> Per the project rule, `CLAUDE.md` lives in the parent repo (`t4lk/`), a different git repo. Commit it there.

- [ ] **Step 1: Update the endpoints, config, and database sections of `CLAUDE.md`**

Apply these changes to `/home/nbe/projects/avp/t4lk/CLAUDE.md`:

- Endpoints table: keep the three REST/health endpoints; add a row for the admin API; note that `/v1/*`
  now requires `Authorization: Bearer <token>` while `/health` and `/admin` (separate `ADMIN_TOKEN`) differ.
- Config table: remove `ASR_MODEL`, `BOOSTING_ALPHA`, `BOOSTING_CONTEXT_SCORE`, `BOOSTING_DEPTH_SCALING`;
  ensure `WHISPER_MODEL` is the model; add `DATABASE_URL` and `ADMIN_TOKEN`.
- Replace "Base de donnees : aucune (service interne sans auth)" with
  "Base de donnees : SQLite (tokens uniquement, volume `token-data`)".
- Remove any WebSocket / Parakeet / NeMo mentions from the server description and architecture diagram;
  state the server is faster-whisper REST-only with Bearer token auth.
- Add a short "Token bootstrap" note: set `ADMIN_TOKEN`, open `/admin/`, create a token, configure the client.

- [ ] **Step 2: Commit (in the parent repo)**

```bash
cd /home/nbe/projects/avp/t4lk
git add CLAUDE.md
git commit -m "docs: update server docs for whisper-only REST + token auth"
```

---

## Final verification (run after all tasks)

- [ ] **Full test suite with coverage**

Run: `cd t4lk-server && make test`
Expected: PASS, coverage ≥ 80%.

- [ ] **Lint + types**

Run: `cd t4lk-server && make lint`
Expected: ruff clean, mypy clean.

- [ ] **Manual smoke (optional, requires GPU/Docker)**

```bash
cd t4lk-server
export ADMIN_TOKEN=$(make token)
make build
# open http://localhost:8000/admin/ , create a token, then:
curl -s -H "Authorization: Bearer sk_xxx" -F file=@sample.wav http://localhost:8000/v1/audio/transcriptions
curl -s http://localhost:8000/v1/audio/transcriptions -F file=@sample.wav   # expect 401
curl -s http://localhost:8000/health                                        # expect 200
```

## Out of scope (tracked separately)

- **Client** (`t4lk-client`, separate repo): remove the dead T4lk WebSocket path (`t4lk_connection.rs`,
  `connect_t4lk`), use the REST endpoint with an `sk_…` token minted via `/admin`. Its own spec → plan → execute.
- Deleting the abandoned `feature/T4LK-000_*`, `feature/T4LK-001_*`, `feature/dual-engine-*` branches.
