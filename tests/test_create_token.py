"""Tests for the token-minting CLI helper."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from rest.auth.tokens import get_token_by_plain
from rest.create_token import mint_token
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


async def test_mint_token_returns_and_persists(session_maker):
    plain = await mint_token("laptop", session_maker=session_maker)
    assert plain.startswith("sk_")
    async with session_maker() as s:
        found = await get_token_by_plain(s, plain)
        assert found is not None
        assert found.name == "laptop"
