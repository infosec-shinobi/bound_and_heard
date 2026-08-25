from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Book, ReadingEvent, ScrapeJobItem, ScrapeSnapshot
from app.scrapers.libby_progress import infer_status, parse_libby_progress
from app.services.scrape_progress import approximate_completion_date, date_to_datetime, has_manual_correction


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair Libby journey start/completion dates from stored scrape snapshots.")
    parser.add_argument("--book-id", type=int, action="append", dest="book_ids", help="Limit repair to a book ID. Can be repeated.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Defaults to dry-run.")
    parser.add_argument(
        "--force-completed",
        action="store_true",
        help="Replace completed_on even when it does not look like the old scrape-date bug.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        books = _books(db, args.book_ids)
        changed = 0
        for book in books:
            item = _latest_successful_item_with_snapshot(db, book.id)
            if item is None:
                print(f"book {book.id}: skipped, no successful scrape snapshot")
                continue
            snapshot = _best_snapshot(item.snapshots)
            if snapshot is None:
                print(f"book {book.id}: skipped, no readable scrape snapshot")
                continue
            content = Path(snapshot.file_path).read_text(encoding="utf-8")
            parsed = parse_libby_progress(content, content_type=snapshot.content_type)
            if parsed.progress_percent is None and snapshot.progress_percent is not None:
                parsed = replace(
                    parsed,
                    progress_percent=snapshot.progress_percent,
                    status_inferred=infer_status(snapshot.progress_percent),
                )
            inferred_completed_on = approximate_completion_date(parsed, item) if parsed.status_inferred == "completed" else None

            changes: dict[str, object] = {}
            if parsed.started_on is not None and book.started_on is None and not has_manual_correction(
                db,
                book_id=book.id,
                field_name="started_on",
            ):
                changes["started_on"] = parsed.started_on

            if inferred_completed_on is not None and not has_manual_correction(db, book_id=book.id, field_name="completed_on"):
                can_update_completed = (
                    book.completed_on is None
                    or args.force_completed
                    or _looks_like_old_scrape_date_bug(db, book=book, item=item, snapshot=snapshot)
                )
                if can_update_completed and book.completed_on != inferred_completed_on:
                    changes["completed_on"] = inferred_completed_on

            if not changes:
                print(f"book {book.id}: no changes")
                continue

            print(
                f"book {book.id}: {book.title!r} "
                + ", ".join(f"{field} {getattr(book, field)} -> {value}" for field, value in changes.items())
            )
            changed += 1

            if args.apply:
                for field, value in changes.items():
                    setattr(book, field, value)
                event = _scraped_event_for_item(db, item=item, event_type="completed")
                if event is not None and inferred_completed_on is not None:
                    event.event_date = date_to_datetime(inferred_completed_on)
                    raw_data = event.raw_data if isinstance(event.raw_data, dict) else {}
                    raw_data.update(
                        {
                            "started_on": parsed.started_on.isoformat() if parsed.started_on else None,
                            "latest_borrowed_on": parsed.latest_borrowed_on.isoformat() if parsed.latest_borrowed_on else None,
                            "inferred_completed_on": inferred_completed_on.isoformat(),
                            "date_repaired_from_snapshot_id": snapshot.id,
                        }
                    )
                    event.raw_data = raw_data

        if args.apply:
            db.commit()
            print(f"applied repairs for {changed} book(s)")
        else:
            db.rollback()
            print(f"dry-run found repairs for {changed} book(s); rerun with --apply to write changes")
    finally:
        db.close()


def _books(db, book_ids: list[int] | None) -> list[Book]:
    statement = select(Book).order_by(Book.id)
    if book_ids:
        statement = statement.where(Book.id.in_(book_ids))
    return list(db.scalars(statement).all())


def _latest_successful_item_with_snapshot(db, book_id: int) -> ScrapeJobItem | None:
    items = db.scalars(
        select(ScrapeJobItem)
        .where(ScrapeJobItem.book_id == book_id, ScrapeJobItem.status == "succeeded")
        .order_by(ScrapeJobItem.id.desc())
    ).all()
    return next((item for item in items if _best_snapshot(item.snapshots) is not None), None)


def _best_snapshot(snapshots: list[ScrapeSnapshot]) -> ScrapeSnapshot | None:
    existing = [snapshot for snapshot in snapshots if Path(snapshot.file_path).exists()]
    text_snapshots = [snapshot for snapshot in existing if snapshot.snapshot_type == "text"]
    candidates = text_snapshots or existing
    return sorted(candidates, key=lambda snapshot: snapshot.id, reverse=True)[0] if candidates else None


def _scraped_event_for_item(db, *, item: ScrapeJobItem, event_type: str) -> ReadingEvent | None:
    return db.scalars(
        select(ReadingEvent).where(
            ReadingEvent.source == "scraped",
            ReadingEvent.source_event_id == f"scrape_item:{item.id}:{event_type}",
        )
    ).first()


def _looks_like_old_scrape_date_bug(db, *, book: Book, item: ScrapeJobItem, snapshot: ScrapeSnapshot) -> bool:
    if book.completed_on is None:
        return True
    event = _scraped_event_for_item(db, item=item, event_type="completed")
    possible_scrape_dates = {
        value.date()
        for value in (item.finished_at, item.last_attempted_at, snapshot.created_at, event.event_date if event else None)
        if value is not None
    }
    return book.completed_on in possible_scrape_dates


if __name__ == "__main__":
    main()
