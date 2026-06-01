"""FastAPI auth and usage-logging dependencies."""

import time
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from rest.auth.tokens import get_token_by_plain, update_token_usage
from rest.db.database import get_db
from rest.db.models import Token, UsageLog

security = HTTPBearer(auto_error=False)


async def verify_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Verify the Bearer token, record usage count, and expose token_id.

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


async def record_usage(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncGenerator[None, None]:
    """Write a UsageLog row after the endpoint completes (authenticated requests).

    Runs as a yield dependency so the measured time covers the endpoint execution.
    Reads request.state.token_id set by verify_token and shares its get_db session,
    which commits the row during its own teardown. A BaseHTTPMiddleware cannot see
    request.state set by a route dependency, so this runs in the request scope.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        token_id = getattr(request.state, "token_id", None)
        if token_id is not None:
            db.add(
                UsageLog(
                    token_id=token_id,
                    endpoint=request.url.path,
                    process_time=round(time.perf_counter() - start, 4),
                )
            )


CurrentToken = Annotated[Token, Depends(verify_token)]
