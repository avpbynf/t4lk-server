"""Authentication module for whisper-server.

This module provides token-based authentication for the API.

Main components:
- Token generation and hashing (using bcrypt via passlib)
- CRUD operations for tokens in the database
- FastAPI dependencies for protecting endpoints
"""

from auth.dependencies import CurrentToken, verify_token
from auth.tokens import (
    create_token,
    generate_token,
    get_token_by_id,
    get_token_by_plain,
    get_token_stats,
    hash_token,
    list_tokens,
    revoke_token,
    update_token_usage,
    verify_token_hash,
)

__all__ = [
    # Dependencies
    "verify_token",
    "CurrentToken",
    # Token functions
    "generate_token",
    "hash_token",
    "verify_token_hash",
    # CRUD functions
    "create_token",
    "get_token_by_id",
    "get_token_by_plain",
    "get_token_stats",
    "list_tokens",
    "revoke_token",
    "update_token_usage",
]
