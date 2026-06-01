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
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(admin_security)
    ],
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
    return TokenListResponse(tokens=[TokenResponse.model_validate(t) for t in tokens])


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
