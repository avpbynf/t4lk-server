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
