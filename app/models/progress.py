from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class BookProgress(Base):
    __tablename__ = "book_progress"
    __table_args__ = (UniqueConstraint("book_id", name="uq_book_progress_book_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    progress_percent: Mapped[float | None] = mapped_column(Float)
    position_seconds: Mapped[int | None] = mapped_column(Integer)
    position_pages: Mapped[int | None] = mapped_column(Integer)
    total_seconds: Mapped[int | None] = mapped_column(Integer)
    total_pages: Mapped[int | None] = mapped_column(Integer)
    enjoyed_seconds: Mapped[int | None] = mapped_column(Integer)
    read_count: Mapped[int | None] = mapped_column(Integer)
    last_borrowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scraped_borrowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_inferred: Mapped[str | None] = mapped_column(String(50), index=True)
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

    user: Mapped[User] = relationship(back_populates="book_progress")
    book: Mapped[Book] = relationship(back_populates="progress")
