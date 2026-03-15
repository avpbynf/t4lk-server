"""Token management for API authentication.

This module provides functions for generating, hashing, verifying, and managing
API tokens stored in the database.
"""

import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Token

# Token prefix for identification
TOKEN_PREFIX = "sk_"
TOKEN_BYTES = 16  # 32 hex characters


def generate_token() -> tuple[str, str]:
    """
    Generate a new API token.

    Returns:
        tuple[str, str]: A tuple of (plain_token, hashed_token).
            - plain_token: The token in format "sk_" + 32 random hex chars
            - hashed_token: The SHA256 hash of the plain token
    """
    # Generate 16 random bytes = 32 hex characters
    random_part = secrets.token_hex(TOKEN_BYTES)
    plain_token = f"{TOKEN_PREFIX}{random_part}"
    hashed_token = hash_token(plain_token)
    return plain_token, hashed_token


def hash_token(token: str) -> str:
    """
    Hash a token using SHA256.

    For API tokens (already high-entropy random strings), SHA256 is sufficient.
    No salt needed since each token is unique.

    Args:
        token: The plain text token to hash

    Returns:
        str: The SHA256 hash of the token (hex encoded)
    """
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token_hash(plain: str, hashed: str) -> bool:
    """
    Verify a plain token against its hash.

    Args:
        plain: The plain text token
        hashed: The SHA256 hash to verify against

    Returns:
        bool: True if the token matches the hash, False otherwise
    """
    return secrets.compare_digest(hash_token(plain), hashed)


# --- CRUD Functions (async, using SQLAlchemy session) ---


async def create_token(db: AsyncSession, name: str) -> tuple[Token, str]:
    """
    Create a new token in the database.

    Args:
        db: The async database session
        name: A human-readable name for the token

    Returns:
        tuple[Token, str]: A tuple of (Token model, plain_token).
            The plain token is only returned at creation time and cannot
            be retrieved later.
    """
    plain_token, hashed_token = generate_token()

    token = Token(
        key_hash=hashed_token,
        name=name,
    )

    db.add(token)
    await db.flush()  # Get the ID assigned
    await db.refresh(token)

    return token, plain_token


async def get_token_by_plain(db: AsyncSession, plain_token: str) -> Token | None:
    """
    Find a token by verifying its hash against stored hashes.

    This function iterates through all active tokens and verifies the
    plain token against each hash. This is necessary because bcrypt
    hashes are salted and cannot be looked up directly.

    Args:
        db: The async database session
        plain_token: The plain text token to look up

    Returns:
        Token | None: The matching Token model if found and active, None otherwise
    """
    # Only check active tokens
    result = await db.execute(select(Token).where(Token.is_active == True))
    tokens = result.scalars().all()

    for token in tokens:
        if verify_token_hash(plain_token, token.key_hash):
            return token

    return None


async def list_tokens(db: AsyncSession, include_inactive: bool = False) -> list[Token]:
    """
    List all tokens in the database.

    Args:
        db: The async database session
        include_inactive: If True, include revoked/inactive tokens

    Returns:
        list[Token]: List of Token models
    """
    if include_inactive:
        result = await db.execute(select(Token).order_by(Token.created_at.desc()))
    else:
        result = await db.execute(
            select(Token)
            .where(Token.is_active == True)
            .order_by(Token.created_at.desc())
        )

    return list(result.scalars().all())


async def revoke_token(db: AsyncSession, token_id: UUID) -> bool:
    """
    Revoke a token by setting is_active=False.

    Args:
        db: The async database session
        token_id: The UUID of the token to revoke

    Returns:
        bool: True if the token was found and revoked, False otherwise
    """
    result = await db.execute(select(Token).where(Token.id == token_id))
    token = result.scalar_one_or_none()

    if token is None:
        return False

    token.is_active = False
    await db.flush()

    return True


async def update_token_usage(db: AsyncSession, token: Token) -> None:
    """
    Update a token's usage statistics.

    Increments the usage_count and updates last_used_at to the current time.

    Args:
        db: The async database session
        token: The Token model to update
    """
    token.usage_count += 1
    token.last_used_at = datetime.utcnow()
    await db.flush()


async def get_token_by_id(db: AsyncSession, token_id: UUID) -> Token | None:
    """
    Get a token by its UUID.

    Args:
        db: The async database session
        token_id: The UUID of the token

    Returns:
        Token | None: The Token model if found, None otherwise
    """
    result = await db.execute(select(Token).where(Token.id == token_id))
    return result.scalar_one_or_none()


async def get_token_stats(db: AsyncSession, token_id: UUID) -> dict | None:
    """
    Get detailed usage statistics for a token.

    Args:
        db: The async database session
        token_id: The UUID of the token

    Returns:
        dict | None: A dictionary containing usage statistics, or None if token not found.
            Includes: token_id, token_name, total_requests, usage_count,
            endpoint_breakdown, average_process_time, last_used_at, recent_logs
    """
    from sqlalchemy.orm import selectinload

    from db.models import UsageLog

    # Get token with usage logs eagerly loaded
    result = await db.execute(
        select(Token)
        .where(Token.id == token_id)
        .options(selectinload(Token.usage_logs))
    )
    token = result.scalar_one_or_none()

    if token is None:
        return None

    usage_logs = token.usage_logs
    total_requests = len(usage_logs)

    # Group requests by endpoint
    endpoint_breakdown: dict[str, int] = {}
    total_process_time = 0.0
    process_time_count = 0

    for log in usage_logs:
        endpoint_breakdown[log.endpoint] = endpoint_breakdown.get(log.endpoint, 0) + 1
        if log.process_time is not None:
            total_process_time += log.process_time
            process_time_count += 1

    avg_process_time = (
        round(total_process_time / process_time_count, 3)
        if process_time_count > 0
        else None
    )

    # Get the 10 most recent logs
    recent_logs = sorted(usage_logs, key=lambda x: x.timestamp, reverse=True)[:10]

    return {
        "token_id": str(token.id),
        "token_name": token.name,
        "total_requests": total_requests,
        "usage_count": token.usage_count,
        "endpoint_breakdown": endpoint_breakdown,
        "average_process_time": avg_process_time,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "recent_logs": [
            {
                "id": str(log.id),
                "endpoint": log.endpoint,
                "timestamp": log.timestamp.isoformat(),
                "process_time": log.process_time,
            }
            for log in recent_logs
        ],
    }
