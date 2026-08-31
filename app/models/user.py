from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.enrichment import MetadataEnrichmentRun
    from app.models.genre import BookGenre, Genre
    from app.models.import_record import Import
    from app.models.book import Book
    from app.models.progress import BookProgress
    from app.models.reading_event import ReadingEvent
    from app.models.recap import Recap
    from app.models.scrape import ScrapeJob
    from app.models.series import LibbySeriesHint, LibbySeriesSnapshot, Series


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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

    books: Mapped[list[Book]] = relationship(back_populates="user")
    imports: Mapped[list[Import]] = relationship(back_populates="user")
    reading_events: Mapped[list[ReadingEvent]] = relationship(back_populates="user")
    book_progress: Mapped[list[BookProgress]] = relationship(back_populates="user")
    scrape_jobs: Mapped[list[ScrapeJob]] = relationship(back_populates="user")
    series: Mapped[list[Series]] = relationship(back_populates="user")
    libby_series_hints: Mapped[list[LibbySeriesHint]] = relationship(back_populates="user")
    libby_series_snapshots: Mapped[list[LibbySeriesSnapshot]] = relationship(back_populates="user")
    metadata_enrichment_runs: Mapped[list[MetadataEnrichmentRun]] = relationship(back_populates="user")
    genres: Mapped[list[Genre]] = relationship(back_populates="user")
    book_genres: Mapped[list[BookGenre]] = relationship(back_populates="user")
    recaps: Mapped[list[Recap]] = relationship(back_populates="user")
