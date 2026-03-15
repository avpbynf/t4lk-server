"""SQLAlchemy 2.0 models for the whisper-server database."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class Token(Base):
    """Model for storing API tokens."""

    __tablename__ = "tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key_hash: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationship to usage logs
    usage_logs: Mapped[list["UsageLog"]] = relationship(
        "UsageLog", back_populates="token", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Token(id={self.id}, name='{self.name}', is_active={self.is_active})>"


class UsageLog(Base):
    """Model for tracking API usage."""

    __tablename__ = "usage_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_id: Mapped[UUID] = mapped_column(ForeignKey("tokens.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    process_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationship to token
    token: Mapped["Token"] = relationship("Token", back_populates="usage_logs")

    def __repr__(self) -> str:
        return f"<UsageLog(id={self.id}, endpoint='{self.endpoint}', timestamp={self.timestamp})>"
