"""CLI to mint an API token: ``python -m rest.create_token <name>``.

Runs against the same database as the server (DATABASE_URL). Inside Docker:
``docker compose exec stt uv run python -m rest.create_token laptop``.
Prints the plain ``sk_...`` token once. It cannot be retrieved later.
"""

import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rest.auth.tokens import create_token
from rest.db.database import async_session_maker, init_db


async def mint_token(
    name: str,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
) -> str:
    """Create a token and return its plain value, initializing the DB if needed.

    Args:
        name: Human-readable token name (e.g. the client machine name).
        session_maker: Session factory; defaults to the app's (tests inject one).

    Returns:
        The plain ``sk_...`` token string (shown once).
    """
    maker = session_maker or async_session_maker
    if session_maker is None:
        await init_db()
    async with maker() as session:
        _, plain = await create_token(session, name)
        await session.commit()
    return plain


def main() -> None:
    """Read the token name from argv, mint it, and print the plain token."""
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("Usage: python -m rest.create_token <name>", file=sys.stderr)
        raise SystemExit(2)
    print(asyncio.run(mint_token(sys.argv[1].strip())))


if __name__ == "__main__":
    main()
