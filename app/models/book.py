from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.progress import BookProgress
    from app.models.reading_event import ReadingEvent
    from app.models.user import User


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    subtitle: Mapped[str | None] = mapped_column(String(500))
    primary_author_name: Mapped[str | None] = mapped_column(String(300), index=True)
    isbn10: Mapped[str | None] = mapped_column(String(10), index=True)
    isbn13: Mapped[str | None] = mapped_column(String(13), index=True)
    libby_title_id: Mapped[str | None] = mapped_column(String(100), index=True)
    libby_share_url: Mapped[str | None] = mapped_column(String(1000))
    publisher: Mapped[str | None] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
    rating: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    started_on: Mapped[date | None] = mapped_column(Date)
    completed_on: Mapped[date | None] = mapped_column(Date, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    audio_seconds: Mapped[int | None] = mapped_column(Integer)
    manual_progress_percent: Mapped[float | None] = mapped_column(Float)
    cover_url: Mapped[str | None] = mapped_column(String(1000))
    cover_color: Mapped[str | None] = mapped_column(String(20))
    title_source: Mapped[str | None] = mapped_column(String(50))
    author_source: Mapped[str | None] = mapped_column(String(50))
    metadata_source: Mapped[str | None] = mapped_column(String(50))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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

    user: Mapped[User] = relationship(back_populates="books")
    reading_events: Mapped[list[ReadingEvent]] = relationship(back_populates="book")
    progress: Mapped[BookProgress | None] = relationship(back_populates="book")
