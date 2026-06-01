"""SQLAlchemy 2.0 models for the token database."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (for SQLite storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class Token(Base):
    """An API token, stored as a SHA256 hash (the plain token is shown once)."""

    __tablename__ = "tokens"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    usage_logs: Mapped[list["UsageLog"]] = relationship(
        "UsageLog", back_populates="token", cascade="all, delete-orphan"
    )


class UsageLog(Base):
    """One row per authenticated request, used for usage statistics."""

    __tablename__ = "usage_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    token_id: Mapped[UUID] = mapped_column(ForeignKey("tokens.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    process_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    token: Mapped["Token"] = relationship("Token", back_populates="usage_logs")
