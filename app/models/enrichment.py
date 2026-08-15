from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class MetadataCacheEntry(Base):
    __tablename__ = "metadata_cache_entries"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "lookup_type",
            "normalized_query",
            "response_checksum",
            name="uq_metadata_cache_provider_lookup_query_checksum",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    lookup_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    normalized_query: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    response_checksum: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict | list | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MetadataEnrichmentRun(Base):
    __tablename__ = "metadata_enrichment_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), index=True)
    provider: Mapped[str | None] = mapped_column(String(50), index=True)
    lookup_type: Mapped[str | None] = mapped_column(String(50), index=True)
    normalized_query: Mapped[str | None] = mapped_column(String(1000), index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    cache_entry_id: Mapped[int | None] = mapped_column(ForeignKey("metadata_cache_entries.id"), index=True)
    fields_applied: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped[User] = relationship(back_populates="metadata_enrichment_runs")
    book: Mapped[Book | None] = relationship(back_populates="metadata_enrichment_runs")
    cache_entry: Mapped[MetadataCacheEntry | None] = relationship()
