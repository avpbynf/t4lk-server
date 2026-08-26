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
    """Generate a new token. Returns (plain "sk_...", sha256_hex_hash)."""
    plain = f"{TOKEN_PREFIX}{secrets.token_hex(TOKEN_BYTES)}"
    return plain, hash_token(plain)


def hash_token(token: str) -> str:
    """Return the SHA256 hex digest of a token."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token_hash(plain: str, hashed: str) -> bool:
    """Constant-time comparison of a plain token against a stored hash."""
    return secrets.compare_digest(hash_token(plain), hashed)


async def create_token(db: AsyncSession, name: str) -> tuple[Token, str]:
    """Create and persist a token. Returns (model, plain), where plain is shown once."""
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
