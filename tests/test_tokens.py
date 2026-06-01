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
        _, plain = await create_token(s, "laptop")
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
        await create_token(s, "active")
        t2, _ = await create_token(s, "revoked")
        await s.commit()
        await revoke_token(s, t2.id)
        await s.commit()
        active = await list_tokens(s)
        assert [t.name for t in active] == ["active"]
        all_tokens = await list_tokens(s, include_inactive=True)
        assert len(all_tokens) == 2
