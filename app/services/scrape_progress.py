from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, BookProgress, LibbySeriesHint, ReadingEvent, ScrapeJobItem
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


def date_to_datetime(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def approximate_completion_date(parsed: LibbyProgressParseResult, item: ScrapeJobItem) -> date | None:
    latest_borrowed_on = parsed.latest_borrowed_on
    if latest_borrowed_on is None and item.latest_borrowed_at is not None:
        latest_borrowed_on = item.latest_borrowed_at.date()
    if latest_borrowed_on is None:
        return None
    return latest_borrowed_on + timedelta(weeks=3)


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
    inferred_completed_on = approximate_completion_date(parsed, item) if parsed.status_inferred == "completed" else None
    event_date = date_to_datetime(inferred_completed_on) if inferred_completed_on is not None else observed_at
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
            event_date=event_date,
        )
        db.add(event)
    event.event_type = event_type
    event.event_date = event_date
    event.progress_percent = parsed.progress_percent
    event.raw_data = {
        "parser_version": parsed.parser_version,
        "progress_text": parsed.progress_text,
        "started_on": parsed.started_on.isoformat() if parsed.started_on else None,
        "latest_borrowed_on": parsed.latest_borrowed_on.isoformat() if parsed.latest_borrowed_on else None,
        "inferred_completed_on": inferred_completed_on.isoformat() if inferred_completed_on else None,
    }

    if parsed.series_hint is not None:
        upsert_libby_series_hint(db, item=item, parsed=parsed)

    if parsed.started_on is not None and book.started_on is None and not has_manual_correction(
        db,
        book_id=book.id,
        field_name="started_on",
    ):
        book.started_on = parsed.started_on

    if parsed.status_inferred == "completed":
        if inferred_completed_on is not None and book.completed_on is None and not has_manual_correction(
            db,
            book_id=book.id,
            field_name="completed_on",
        ):
            book.completed_on = inferred_completed_on
        if book.status not in {"completed", "abandoned"} and not has_manual_correction(
            db,
            book_id=book.id,
            field_name="status",
        ):
            book.status = "completed"

    return progress


def upsert_libby_series_hint(db: Session, *, item: ScrapeJobItem, parsed: LibbyProgressParseResult) -> LibbySeriesHint | None:
    hint = parsed.series_hint
    if hint is None:
        return None
    book = db.get(Book, item.book_id)
    if book is None:
        raise ValueError("Scrape item book does not exist.")
    existing = db.scalars(
        select(LibbySeriesHint).where(
            LibbySeriesHint.book_id == book.id,
            LibbySeriesHint.libby_series_key == hint.libby_series_key,
        )
    ).first()
    if existing is None:
        existing = LibbySeriesHint(
            user_id=book.user_id,
            book_id=book.id,
            libby_series_key=hint.libby_series_key,
            libby_series_url=hint.libby_series_url,
            raw_label=hint.raw_label,
        )
        db.add(existing)
    existing.scrape_item_id = item.id
    existing.libby_series_url = hint.libby_series_url
    existing.raw_label = hint.raw_label
    existing.series_name = hint.series_name
    existing.position = hint.position
    if existing.status != "applied":
        existing.status = "pending"
    db.flush()
    return existing
