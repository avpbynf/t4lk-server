"""Tests for the token database layer (real in-memory SQLite)."""

import pytest
from sqlalchemy import select
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
        fetched = (
            await s.execute(select(Token).where(Token.id == token_id))
        ).scalar_one()
        assert fetched.name == "laptop"
        assert fetched.is_active is True
        assert fetched.usage_count == 0
        assert str(fetched.id) == str(token_id)


async def test_usage_log_fk_relationship(session_maker):
    async with session_maker() as s:
        token = Token(key_hash="h", name="t")
        s.add(token)
        await s.flush()
        s.add(
            UsageLog(
                token_id=token.id,
                endpoint="/v1/audio/transcriptions",
                process_time=1.2,
            )
        )
        await s.commit()
        await s.refresh(token, attribute_names=["usage_logs"])
        assert len(token.usage_logs) == 1
        assert token.usage_logs[0].endpoint == "/v1/audio/transcriptions"
