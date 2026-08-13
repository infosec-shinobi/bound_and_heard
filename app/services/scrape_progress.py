from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, BookProgress, ReadingEvent, ScrapeJobItem
from app.scrapers.libby_progress import LibbyProgressParseResult


def has_manual_correction(db: Session, *, book_id: int, field_name: str) -> bool:
    events = db.scalars(
        select(ReadingEvent).where(
            ReadingEvent.book_id == book_id,
            ReadingEvent.source == "manual",
            ReadingEvent.event_type == "manually_corrected",
        )
    ).all()
    for event in events:
        raw_data = event.raw_data or {}
        changed_fields = raw_data.get("changed_fields") if isinstance(raw_data, dict) else None
        if isinstance(changed_fields, dict) and field_name in changed_fields:
            return True
    return False


def approximate_completion_date(observed_at: datetime) -> date:
    return observed_at.date()


def apply_scraped_progress(
    db: Session,
    *,
    item: ScrapeJobItem,
    parsed: LibbyProgressParseResult,
    observed_at: datetime | None = None,
) -> BookProgress:
    observed_at = observed_at or datetime.now(timezone.utc)
    book = db.get(Book, item.book_id)
    if book is None:
        raise ValueError("Scrape item book does not exist.")

    progress = db.scalars(select(BookProgress).where(BookProgress.book_id == book.id)).first()
    if progress is None:
        progress = BookProgress(user_id=book.user_id, book_id=book.id, source="scraped")
        db.add(progress)

    manual_progress_protected = book.manual_progress_percent is not None or has_manual_correction(
        db,
        book_id=book.id,
        field_name="manual_progress_percent",
    )
    if not manual_progress_protected:
        progress.progress_percent = parsed.progress_percent

    progress.source = "scraped"
    progress.position_pages = parsed.position_pages
    progress.total_pages = parsed.total_pages
    progress.position_seconds = parsed.position_seconds
    progress.total_seconds = parsed.total_seconds
    progress.enjoyed_seconds = parsed.enjoyed_seconds
    progress.last_borrowed_at = item.latest_borrowed_at
    progress.last_scraped_borrowed_at = item.latest_borrowed_at
    progress.observed_at = observed_at
    progress.scraped_at = observed_at
    progress.status_inferred = parsed.status_inferred

    event_type = "completed" if parsed.status_inferred == "completed" else "progress_seen"
    source_event_id = f"scrape_item:{item.id}:{event_type}"
    event = db.scalars(
        select(ReadingEvent).where(
            ReadingEvent.user_id == book.user_id,
            ReadingEvent.source == "scraped",
            ReadingEvent.source_event_id == source_event_id,
        )
    ).first()
    if event is None:
        event = ReadingEvent(
            user_id=book.user_id,
            book_id=book.id,
            source="scraped",
            source_event_id=source_event_id,
            event_type=event_type,
            event_date=observed_at,
        )
        db.add(event)
    event.event_type = event_type
    event.event_date = observed_at
    event.progress_percent = parsed.progress_percent
    event.raw_data = {"parser_version": parsed.parser_version, "progress_text": parsed.progress_text}

    if parsed.status_inferred == "completed":
        if book.completed_on is None and not has_manual_correction(db, book_id=book.id, field_name="completed_on"):
            book.completed_on = approximate_completion_date(observed_at)
        if book.status not in {"completed", "abandoned"} and not has_manual_correction(
            db,
            book_id=book.id,
            field_name="status",
        ):
            book.status = "completed"

    return progress
