from __future__ import annotations

from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Book, BookGenre, ReadingEvent, Series, SeriesBook
from app.services import analytics


MAX_RECENT_ITEMS = 10
MAX_RANKED_ITEMS = 10
COMPLETION_EVENT_TYPES = {"completed", "manually_completed"}


def summarize_reading_history(
    db: Session,
    *,
    user_id: int,
    period: analytics.PeriodRange | None = None,
    include_note_summaries: bool = False,
) -> dict[str, object]:
    """Build safe, deterministic recommendation context from normalized local data."""
    period = period or analytics.all_time_range()
    books = _load_books(db, user_id=user_id)
    series_rows = _load_series(db, user_id=user_id)
    completed_books = [_completed_book_summary(book, completed_on) for book, completed_on in _completed_books(books, period)]
    recent_completions = sorted(
        completed_books,
        key=lambda item: (item["completed_on"] is None, item["completed_on"] or "", item["title"].casefold()),
        reverse=True,
    )[:MAX_RECENT_ITEMS]
    recent_abandons = _recent_abandons(books, period)[:MAX_RECENT_ITEMS]
    active_series = [_series_summary(series) for series in series_rows if series.status in {"active", "paused", "unknown"}]
    active_series = sorted(active_series, key=lambda item: item["name"].casefold())

    summary: dict[str, object] = {
        "period": _period_summary(period),
        "totals": {
            "completed_books": len(completed_books),
            "pages_read": analytics.pages_read(db, user_id=user_id, period=period),
            "audiobook_seconds": analytics.audiobook_seconds(db, user_id=user_id, period=period),
            "lifetime_enjoyed_seconds": analytics.lifetime_enjoyed_seconds(db, user_id=user_id),
        },
        "favorites": {
            "authors": [_ranked_value(value) for value in analytics.top_authors(db, user_id=user_id, period=period, limit=MAX_RANKED_ITEMS)],
            "genres": [_ranked_value(value) for value in analytics.top_genres(db, user_id=user_id, period=period, limit=MAX_RANKED_ITEMS)],
            "formats": _format_breakdown(analytics.format_breakdown(db, user_id=user_id, period=period)),
            "series": _favorite_series(series_rows, period),
        },
        "preferences": _preference_summary(completed_books),
        "recent": {
            "completed": recent_completions,
            "abandoned": recent_abandons,
        },
        "series": {
            "active_or_paused": active_series,
            "next_unread": [item for item in (_next_unread_summary(series) for series in series_rows) if item is not None][:MAX_RECENT_ITEMS],
            "planned_unread": _planned_entries(series_rows)[:MAX_RECENT_ITEMS],
        },
        "safety": {
            "raw_import_files_included": False,
            "raw_scrape_snapshots_included": False,
            "browser_profile_included": False,
            "secrets_included": False,
            "raw_provider_responses_included": False,
            "full_notes_included": include_note_summaries,
        },
    }
    if include_note_summaries:
        summary["note_summaries"] = _note_summaries(books)
    return summary


def _load_books(db: Session, *, user_id: int) -> list[Book]:
    return list(
        db.scalars(
            select(Book)
            .where(Book.user_id == user_id, Book.archived_at.is_(None))
            .options(
                selectinload(Book.reading_events),
                selectinload(Book.progress),
                selectinload(Book.genre_entries).selectinload(BookGenre.genre),
            )
            .order_by(Book.title.asc(), Book.id.asc())
        ).all()
    )


def _load_series(db: Session, *, user_id: int) -> list[Series]:
    return list(
        db.scalars(
            select(Series)
            .where(Series.user_id == user_id)
            .options(
                selectinload(Series.books).selectinload(SeriesBook.book).selectinload(Book.reading_events),
                selectinload(Series.books).selectinload(SeriesBook.book).selectinload(Book.progress),
            )
            .order_by(Series.name.asc(), Series.id.asc())
        ).all()
    )


def _completed_books(books: list[Book], period: analytics.PeriodRange) -> list[tuple[Book, date | None]]:
    completed: list[tuple[Book, date | None]] = []
    for book in books:
        dates = _completion_dates(book)
        matching_dates = [value for value in dates if period.contains(value)]
        if matching_dates:
            completed.append((book, min(matching_dates)))
        elif not dates and period.start is None and period.end is None and _has_undated_completion_evidence(book):
            completed.append((book, None))
    return sorted(completed, key=lambda item: (item[1] is None, item[1] or date.min, item[0].title.casefold()))


def _completed_book_summary(book: Book, completed_on: date | None) -> dict[str, object]:
    return {
        "book_id": book.id,
        "title": book.title,
        "author": book.primary_author_name,
        "format": book.format,
        "completed_on": completed_on.isoformat() if completed_on else None,
        "rating": book.rating,
        "genres": _book_genres(book),
        "page_count": book.page_count,
        "audio_seconds": book.audio_seconds,
        "publication_year": book.publication_year,
    }


def _recent_abandons(books: list[Book], period: analytics.PeriodRange) -> list[dict[str, object]]:
    abandoned: list[dict[str, object]] = []
    for book in books:
        abandon_dates = sorted(
            event.event_date.date()
            for event in book.reading_events
            if event.event_type == "abandoned" and period.contains(event.event_date.date())
        )
        if book.status == "abandoned" and not abandon_dates and period.contains(book.updated_at.date()):
            abandon_dates.append(book.updated_at.date())
        if not abandon_dates:
            continue
        abandoned.append(
            {
                "book_id": book.id,
                "title": book.title,
                "author": book.primary_author_name,
                "format": book.format,
                "abandoned_on": max(abandon_dates).isoformat(),
                "progress_percent": _current_progress_percent(book),
                "genres": _book_genres(book),
            }
        )
    return sorted(abandoned, key=lambda item: (str(item["abandoned_on"]), str(item["title"]).casefold()), reverse=True)


def _series_summary(series: Series) -> dict[str, object]:
    entries = sorted(series.books, key=lambda entry: (entry.position is None, entry.position or 0, entry.id))
    completed_count = sum(1 for entry in entries if entry.book is not None and _completion_dates(entry.book))
    return {
        "series_id": series.id,
        "name": series.name,
        "status": series.status,
        "wants_to_continue": series.wants_to_continue,
        "known_entries": len(entries),
        "completed_entries": completed_count,
        "planned_unread_entries": sum(1 for entry in entries if entry.book is None),
        "next_unread": _next_unread_summary(series),
    }


def _favorite_series(series_rows: list[Series], period: analytics.PeriodRange) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for series in series_rows:
        completed = 0
        for entry in series.books:
            if entry.book is not None and any(period.contains(value) for value in _completion_dates(entry.book)):
                completed += 1
        if completed:
            rows.append({"series_id": series.id, "name": series.name, "completed_entries": completed})
    return sorted(rows, key=lambda item: (-int(item["completed_entries"]), str(item["name"]).casefold()))[:MAX_RANKED_ITEMS]


def _next_unread_summary(series: Series) -> dict[str, object] | None:
    for entry in sorted(series.books, key=lambda item: (item.position is None, item.position or 0, item.id)):
        if entry.book is None:
            if entry.planned_title:
                return {
                    "series_id": series.id,
                    "series_name": series.name,
                    "title": entry.planned_title,
                    "author": entry.planned_author_name,
                    "format": entry.planned_format,
                    "position": entry.position,
                    "local_book_id": None,
                }
            continue
        if not _completion_dates(entry.book):
            return {
                "series_id": series.id,
                "series_name": series.name,
                "title": entry.book.title,
                "author": entry.book.primary_author_name,
                "format": entry.book.format,
                "position": entry.position,
                "local_book_id": entry.book.id,
            }
    return None


def _planned_entries(series_rows: list[Series]) -> list[dict[str, object]]:
    planned: list[dict[str, object]] = []
    for series in series_rows:
        for entry in series.books:
            if entry.book_id is not None or not entry.planned_title:
                continue
            planned.append(
                {
                    "series_id": series.id,
                    "series_name": series.name,
                    "title": entry.planned_title,
                    "author": entry.planned_author_name,
                    "format": entry.planned_format,
                    "position": entry.position,
                }
            )
    return sorted(planned, key=lambda item: (str(item["series_name"]).casefold(), item["position"] is None, item["position"] or 0))


def _preference_summary(completed_books: list[dict[str, object]]) -> dict[str, object]:
    rated = [book for book in completed_books if book.get("rating") is not None]
    page_counts = [int(book["page_count"]) for book in completed_books if book.get("page_count") is not None and book.get("format") in {"ebook", "physical"}]
    audio_seconds = [int(book["audio_seconds"]) for book in completed_books if book.get("audio_seconds") is not None and book.get("format") == "audiobook"]
    high_rated = [book for book in rated if float(book["rating"]) >= 4]
    return {
        "average_rating": round(sum(float(book["rating"]) for book in rated) / len(rated), 2) if rated else None,
        "highly_rated": high_rated[:MAX_RECENT_ITEMS],
        "typical_page_count": _average_int(page_counts),
        "typical_audiobook_seconds": _average_int(audio_seconds),
    }


def _note_summaries(books: list[Book]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for book in books:
        if not book.notes:
            continue
        clean = " ".join(book.notes.split())
        summaries.append({"book_id": book.id, "title": book.title, "note_excerpt": clean[:200]})
    return summaries[:MAX_RECENT_ITEMS]


def _completion_dates(book: Book) -> list[date]:
    events = sorted((event for event in book.reading_events if event.event_type in COMPLETION_EVENT_TYPES), key=lambda event: event.event_date)
    if events:
        return [event.event_date.date() for event in events]
    if book.completed_on is not None:
        return [book.completed_on]
    if book.status == "completed" and _current_progress_percent(book) is not None and _current_progress_percent(book) >= 98:
        if book.progress is not None and book.progress.observed_at is not None:
            return [book.progress.observed_at.date()]
    return []


def _has_undated_completion_evidence(book: Book) -> bool:
    return book.status == "completed" or (_current_progress_percent(book) is not None and _current_progress_percent(book) >= 98)


def _current_progress_percent(book: Book) -> float | None:
    if book.manual_progress_percent is not None:
        return book.manual_progress_percent
    if book.progress is not None:
        return book.progress.progress_percent
    return None


def _book_genres(book: Book) -> list[str]:
    return sorted({entry.genre.name for entry in book.genre_entries if entry.genre is not None}, key=str.casefold)


def _format_breakdown(values: dict[str, int]) -> list[dict[str, object]]:
    return [{"format": key, "count": values[key]} for key in sorted(values)]


def _ranked_value(value: analytics.RankedValue) -> dict[str, object]:
    return {"label": value.label, "count": value.count}


def _period_summary(period: analytics.PeriodRange) -> dict[str, str | None]:
    return {
        "start": period.start.isoformat() if period.start else None,
        "end": period.end.isoformat() if period.end else None,
    }


def _average_int(values: list[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None
