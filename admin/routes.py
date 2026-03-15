"""Admin API routes for managing API tokens.

These endpoints are protected by a separate ADMIN_TOKEN environment variable,
independent from the user API tokens stored in the database.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.tokens import (
    create_token,
    get_token_by_id,
    get_token_stats,
    list_tokens,
    revoke_token,
)
from db.database import get_db


# --- Pydantic Schemas ---


class TokenCreate(BaseModel):
    """Request body for creating a new token."""

    name: str  # Human-readable name, e.g., "Nicolas PC"


class TokenResponse(BaseModel):
    """Response model for token information (without the actual token)."""

    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool
    usage_count: int

    model_config = {"from_attributes": True}


class TokenCreatedResponse(TokenResponse):
    """Response model returned only at token creation time.

    Includes the plain text token - this is the only time it will be visible!
    """

    token: str


class TokenListResponse(BaseModel):
    """Response model for listing multiple tokens."""

    tokens: list[TokenResponse]


class TokenStatsResponse(BaseModel):
    """Response model for token usage statistics."""

    token_id: str
    token_name: str
    total_requests: int
    usage_count: int
    endpoint_breakdown: dict[str, int]
    average_process_time: float | None
    last_used_at: str | None
    recent_logs: list[dict]


class SuccessResponse(BaseModel):
    """Generic success response."""

    success: bool


# --- Admin Authentication ---


admin_security = HTTPBearer()


async def verify_admin_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(admin_security)],
) -> str:
    """
    Verify the admin Bearer token from the Authorization header.

    This uses the ADMIN_TOKEN environment variable, which is separate from
    the database-stored user tokens.

    Args:
        credentials: The HTTP Authorization credentials extracted by FastAPI

    Returns:
        str: The verified admin token

    Raises:
        HTTPException: 500 if ADMIN_TOKEN is not configured
        HTTPException: 401 if the provided token is invalid
    """
    admin_token = os.getenv("ADMIN_TOKEN")

    if not admin_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_TOKEN not configured",
        )

    if credentials.credentials != admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


# Type alias for admin authentication dependency
AdminAuth = Annotated[str, Depends(verify_admin_token)]


# --- Router ---


router = APIRouter(prefix="/admin", tags=["admin"])


# --- Dashboard ---


@router.get("/", response_class=FileResponse)
async def admin_dashboard():
    """Serve the admin dashboard HTML page."""
    html_path = Path(__file__).parent / "static" / "index.html"
    return FileResponse(html_path, media_type="text/html")


# --- Endpoints ---


@router.post("/tokens", response_model=TokenCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_new_token(
    body: TokenCreate,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenCreatedResponse:
    """
    Create a new API token.

    This is the only time the plain text token will be visible!
    Store it securely - it cannot be retrieved later.

    Args:
        body: The token creation request containing the name
        _admin: Admin authentication (verified automatically)
        db: Database session

    Returns:
        TokenCreatedResponse: The created token info including the plain text token
    """
    token_model, plain_token = await create_token(db, body.name)

    return TokenCreatedResponse(
        id=token_model.id,
        name=token_model.name,
        created_at=token_model.created_at,
        last_used_at=token_model.last_used_at,
        is_active=token_model.is_active,
        usage_count=token_model.usage_count,
        token=plain_token,
    )


@router.get("/tokens", response_model=TokenListResponse)
async def list_all_tokens(
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = False,
) -> TokenListResponse:
    """
    List all API tokens.

    Args:
        _admin: Admin authentication (verified automatically)
        db: Database session
        include_inactive: If true, include revoked/inactive tokens (default: false)

    Returns:
        TokenListResponse: List of all tokens (without their actual token values)
    """
    tokens = await list_tokens(db, include_inactive=include_inactive)

    return TokenListResponse(
        tokens=[
            TokenResponse(
                id=t.id,
                name=t.name,
                created_at=t.created_at,
                last_used_at=t.last_used_at,
                is_active=t.is_active,
                usage_count=t.usage_count,
            )
            for t in tokens
        ]
    )


@router.get("/tokens/{token_id}", response_model=TokenResponse)
async def get_token(
    token_id: UUID,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """
    Get details of a single token.

    Args:
        token_id: The UUID of the token
        _admin: Admin authentication (verified automatically)
        db: Database session

    Returns:
        TokenResponse: The token details (without the actual token value)

    Raises:
        HTTPException: 404 if token not found
    """
    token = await get_token_by_id(db, token_id)

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    return TokenResponse(
        id=token.id,
        name=token.name,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        is_active=token.is_active,
        usage_count=token.usage_count,
    )


@router.delete("/tokens/{token_id}", response_model=SuccessResponse)
async def delete_token(
    token_id: UUID,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SuccessResponse:
    """
    Revoke (soft delete) a token.

    The token will be marked as inactive and can no longer be used for API access.
    The token record is retained for audit purposes.

    Args:
        token_id: The UUID of the token to revoke
        _admin: Admin authentication (verified automatically)
        db: Database session

    Returns:
        SuccessResponse: Success confirmation

    Raises:
        HTTPException: 404 if token not found
    """
    success = await revoke_token(db, token_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    return SuccessResponse(success=True)


@router.get("/tokens/{token_id}/stats", response_model=TokenStatsResponse)
async def get_token_statistics(
    token_id: UUID,
    _admin: AdminAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenStatsResponse:
    """
    Get usage statistics for a token.

    Returns detailed statistics including request counts, endpoint breakdown,
    average processing time, and recent usage logs.

    Args:
        token_id: The UUID of the token
        _admin: Admin authentication (verified automatically)
        db: Database session

    Returns:
        TokenStatsResponse: Detailed usage statistics

    Raises:
        HTTPException: 404 if token not found
    """
    stats = await get_token_stats(db, token_id)

    if stats is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    return TokenStatsResponse(**stats)
