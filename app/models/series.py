from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.scrape import ScrapeJobItem
    from app.models.user import User


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
    wants_to_continue: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown", index=True)
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

    user: Mapped[User] = relationship(back_populates="series")
    books: Mapped[list[SeriesBook]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
        order_by="SeriesBook.position",
    )
    libby_snapshots: Mapped[list[LibbySeriesSnapshot]] = relationship(back_populates="series")


class SeriesBook(Base):
    __tablename__ = "series_books"
    __table_args__ = (UniqueConstraint("series_id", "book_id", name="uq_series_books_series_id_book_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id"), index=True, nullable=False)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id"), index=True)
    position: Mapped[float | None] = mapped_column(Float, index=True)
    position_end: Mapped[float | None] = mapped_column(Float, index=True)
    planned_title: Mapped[str | None] = mapped_column(String(500), index=True)
    planned_author_name: Mapped[str | None] = mapped_column(String(300), index=True)
    planned_format: Mapped[str | None] = mapped_column(String(50), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
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

    series: Mapped[Series] = relationship(back_populates="books")
    book: Mapped[Book | None] = relationship(back_populates="series_entries")


class LibbySeriesHint(Base):
    __tablename__ = "libby_series_hints"
    __table_args__ = (UniqueConstraint("book_id", "libby_series_key", name="uq_libby_series_hints_book_id_series_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True, nullable=False)
    scrape_item_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_job_items.id"), index=True)
    libby_series_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    libby_series_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    raw_label: Mapped[str] = mapped_column(String(500), nullable=False)
    series_name: Mapped[str | None] = mapped_column(String(500), index=True)
    position: Mapped[float | None] = mapped_column(Float, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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

    user: Mapped[User] = relationship(back_populates="libby_series_hints")
    book: Mapped[Book] = relationship(back_populates="libby_series_hints")
    scrape_item: Mapped[ScrapeJobItem | None] = relationship()


class LibbySeriesSnapshot(Base):
    __tablename__ = "libby_series_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id"), index=True, nullable=False)
    libby_series_key: Mapped[str | None] = mapped_column(String(100), index=True)
    libby_series_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128), index=True)
    content_type: Mapped[str | None] = mapped_column(String(200))
    parsed_entry_count: Mapped[int | None] = mapped_column(index=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    user: Mapped[User] = relationship(back_populates="libby_series_snapshots")
    series: Mapped[Series] = relationship(back_populates="libby_snapshots")
