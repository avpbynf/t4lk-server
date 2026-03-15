"""FastAPI dependencies for authentication.

This module provides FastAPI dependency functions for verifying API tokens
in request handlers.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth.tokens import get_token_by_plain, update_token_usage
from db.database import get_db
from db.models import Token

# Security scheme for Bearer token authentication
security = HTTPBearer()


async def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """
    FastAPI dependency that verifies a Bearer token from the Authorization header.

    This dependency:
    1. Extracts the Bearer token from the Authorization header
    2. Looks up the token in the database by verifying against stored hashes
    3. Checks that the token is active
    4. Updates usage statistics (usage_count, last_used_at)
    5. Returns the Token model for use in endpoints

    Usage:
        @app.get("/protected")
        async def protected_endpoint(token: Token = Depends(verify_token)):
            return {"message": f"Hello, {token.name}!"}

    Args:
        credentials: The HTTP Authorization credentials extracted by FastAPI
        db: The async database session

    Returns:
        Token: The verified Token model

    Raises:
        HTTPException: 401 Unauthorized if the token is invalid or inactive
    """
    plain_token = credentials.credentials

    # Look up the token by verifying against stored hashes
    token = await get_token_by_plain(db, plain_token)

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not token.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update usage statistics
    await update_token_usage(db, token)

    return token


# Type alias for use in endpoint signatures
CurrentToken = Annotated[Token, Depends(verify_token)]
