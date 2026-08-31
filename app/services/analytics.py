from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Book, BookGenre, Genre, ReadingEvent, Series, SeriesBook


COMPLETION_EVENT_TYPES = {"completed", "manually_completed"}
COMPLETION_PROGRESS_THRESHOLD = 98
PAGE_FORMATS = {"ebook", "physical"}


@dataclass(frozen=True)
class PeriodRange:
    start: date | None = None
    end: date | None = None

    def contains(self, value: date | None) -> bool:
        if value is None:
            return self.start is None and self.end is None
        if self.start is not None and value < self.start:
            return False
        if self.end is not None and value > self.end:
            return False
        return True


@dataclass(frozen=True)
class MonthCount:
    year: int
    month: int
    count: int


@dataclass(frozen=True)
class RankedValue:
    label: str
    count: int


@dataclass(frozen=True)
class PartialProgressSummary:
    book_count: int
    abandoned_count: int
    average_progress_percent: float | None
    pages_in_progress: int
    audiobook_seconds_in_progress: int


@dataclass(frozen=True)
class RepeatCounts:
    rereads: int
    relistens: int
    repeat_completions: int
    likely_rereads: int = 0
    likely_relistens: int = 0
    likely_repeat_completions: int = 0


@dataclass(frozen=True)
class SeriesActivityCandidate:
    series_id: int
    name: str
    completed_entries: int


@dataclass(frozen=True)
class SeriesNextUnread:
    series_id: int
    series_name: str
    title: str
    position: float | None


@dataclass(frozen=True)
class SeriesActivitySummary:
    total_series: int
    completed_series_entries: int
    active_series_count: int
    planned_entries: int
    collection_range_entries: int
    collection_covered_positions: int
    status_counts: dict[str, int]
    most_active_series: list[SeriesActivityCandidate]
    next_unread: list[SeriesNextUnread]


def month_range(year: int, month: int) -> PeriodRange:
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return PeriodRange(date(year, month, 1), date.fromordinal(next_month.toordinal() - 1))


def quarter_range(year: int, quarter: int) -> PeriodRange:
    if quarter < 1 or quarter > 4:
        raise ValueError("quarter must be between 1 and 4")
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    return PeriodRange(month_range(year, start_month).start, month_range(year, end_month).end)


def year_range(year: int) -> PeriodRange:
    return PeriodRange(date(year, 1, 1), date(year, 12, 31))


def all_time_range() -> PeriodRange:
    return PeriodRange()


def books_completed_by_month(db: Session, *, user_id: int, year: int | None = None) -> list[MonthCount]:
    counts: Counter[tuple[int, int]] = Counter()
    period = year_range(year) if year is not None else all_time_range()
    for completed in _unique_completed_books(db, user_id=user_id, period=period):
        if completed.completed_on is None:
            continue
        counts[(completed.completed_on.year, completed.completed_on.month)] += 1
    return [MonthCount(year=key[0], month=key[1], count=count) for key, count in sorted(counts.items())]


def books_completed_by_period(db: Session, *, user_id: int, period: PeriodRange | None = None) -> int:
    return len(_unique_completed_books(db, user_id=user_id, period=period or all_time_range()))


def format_breakdown(db: Session, *, user_id: int, period: PeriodRange | None = None) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for completed in _unique_completed_books(db, user_id=user_id, period=period or all_time_range()):
        counts[completed.book.format or "unknown"] += 1
    return dict(sorted(counts.items()))


def top_authors(db: Session, *, user_id: int, period: PeriodRange | None = None, limit: int = 10) -> list[RankedValue]:
    counts: Counter[str] = Counter()
    for completed in _unique_completed_books(db, user_id=user_id, period=period or all_time_range()):
        counts[completed.book.primary_author_name or "Unknown Author"] += 1
    return _ranked_values(counts, limit)


def top_genres(db: Session, *, user_id: int, period: PeriodRange | None = None, limit: int = 10) -> list[RankedValue]:
    completed_book_ids = {completed.book.id for completed in _unique_completed_books(db, user_id=user_id, period=period or all_time_range())}
    if not completed_book_ids:
        return []
    rows = db.execute(
        select(Genre.name)
        .join(BookGenre, BookGenre.genre_id == Genre.id)
        .where(BookGenre.book_id.in_(completed_book_ids), BookGenre.user_id == user_id)
    ).all()
    counts = Counter(name for (name,) in rows)
    return _ranked_values(counts, limit)


def pages_read(db: Session, *, user_id: int, period: PeriodRange | None = None) -> int:
    total = 0
    for completed in _unique_completed_books(db, user_id=user_id, period=period or all_time_range()):
        if completed.book.format in PAGE_FORMATS and completed.book.page_count is not None:
            total += completed.book.page_count
    return total


def audiobook_seconds(db: Session, *, user_id: int, period: PeriodRange | None = None) -> int:
    total = 0
    for completed in _unique_completed_books(db, user_id=user_id, period=period or all_time_range()):
        if completed.book.format != "audiobook":
            continue
        if completed.book.audio_seconds is not None:
            total += completed.book.audio_seconds
        elif completed.book.progress is not None and completed.book.progress.total_seconds is not None:
            total += completed.book.progress.total_seconds
    return total


def lifetime_enjoyed_seconds(db: Session, *, user_id: int) -> int:
    total = 0
    for book in _analytics_books(db, user_id=user_id):
        if book.format != "audiobook":
            continue
        if book.progress is not None and book.progress.enjoyed_seconds is not None:
            total += book.progress.enjoyed_seconds
            continue
        duration = book.audio_seconds or (book.progress.total_seconds if book.progress is not None else None)
        if duration is not None:
            total += duration * len(_completion_dates(book))
    return total


def partial_progress_summary(db: Session, *, user_id: int) -> PartialProgressSummary:
    books = _analytics_books(db, user_id=user_id)
    progress_values: list[float] = []
    abandoned_count = 0
    pages_in_progress = 0
    audiobook_seconds_in_progress = 0
    for book in books:
        progress_percent = _current_progress_percent(book)
        progress_status = book.progress.status_inferred if book.progress is not None else None
        is_partial_status = book.status in {"started", "borrowed", "abandoned"} or progress_status in {"started", "borrowed"}
        if not is_partial_status or progress_percent is None or progress_percent >= COMPLETION_PROGRESS_THRESHOLD:
            continue
        progress_values.append(progress_percent)
        if book.status == "abandoned":
            abandoned_count += 1
        if book.format in PAGE_FORMATS and book.page_count is not None:
            pages_in_progress += round(book.page_count * progress_percent / 100)
        if book.format == "audiobook":
            duration = book.audio_seconds or (book.progress.total_seconds if book.progress is not None else None)
            if duration is not None:
                audiobook_seconds_in_progress += round(duration * progress_percent / 100)
    average = sum(progress_values) / len(progress_values) if progress_values else None
    return PartialProgressSummary(
        book_count=len(progress_values),
        abandoned_count=abandoned_count,
        average_progress_percent=average,
        pages_in_progress=pages_in_progress,
        audiobook_seconds_in_progress=audiobook_seconds_in_progress,
    )


def repeat_counts(db: Session, *, user_id: int, period: PeriodRange | None = None) -> RepeatCounts:
    period = period or all_time_range()
    rereads = 0
    relistens = 0
    unknown = 0
    likely_relistens = 0
    for book, events in _completion_events_by_book(db, user_id=user_id).items():
        for index, event in enumerate(events):
            if index == 0 or not period.contains(event.event_date.date()):
                continue
            if book.format == "audiobook":
                relistens += 1
            elif book.format in PAGE_FORMATS:
                rereads += 1
            else:
                unknown += 1
    for book in _analytics_books(db, user_id=user_id):
        likely_relistens += _likely_libby_relistens(book, period=period)
    return RepeatCounts(rereads=rereads, relistens=relistens, repeat_completions=unknown, likely_relistens=likely_relistens)


def series_activity_summary(
    db: Session, *, user_id: int, period: PeriodRange | None = None, limit: int = 5
) -> SeriesActivitySummary:
    period = period or all_time_range()
    series_rows = _analytics_series(db, user_id=user_id)
    status_counts: Counter[str] = Counter()
    completed_by_series: Counter[int] = Counter()
    active_series_ids: set[int] = set()
    series_names: dict[int, str] = {}
    planned_entries = 0
    collection_range_entries = 0
    collection_covered_positions = 0
    next_unread: list[SeriesNextUnread] = []

    for series in series_rows:
        status_counts[series.status or "unknown"] += 1
        series_names[series.id] = series.name
        unread_entry = _next_unread_series_entry(series)
        if unread_entry is not None:
            next_unread.append(unread_entry)
        for entry in series.books:
            if entry.book_id is None:
                planned_entries += 1
            if entry.position is not None and entry.position_end is not None and entry.position_end > entry.position:
                collection_range_entries += 1
                collection_covered_positions += round(entry.position_end - entry.position + 1)
            if entry.book is None:
                continue
            completed_dates = _completion_dates(entry.book)
            if any(period.contains(completed_on) for completed_on in completed_dates):
                completed_by_series[series.id] += 1
                active_series_ids.add(series.id)
            if _current_progress_percent(entry.book) is not None and _current_progress_percent(entry.book) < COMPLETION_PROGRESS_THRESHOLD:
                active_series_ids.add(series.id)

    ranked = sorted(completed_by_series.items(), key=lambda item: (-item[1], series_names[item[0]].casefold()))[:limit]
    return SeriesActivitySummary(
        total_series=len(series_rows),
        completed_series_entries=sum(completed_by_series.values()),
        active_series_count=len(active_series_ids),
        planned_entries=planned_entries,
        collection_range_entries=collection_range_entries,
        collection_covered_positions=collection_covered_positions,
        status_counts=dict(sorted(status_counts.items())),
        most_active_series=[
            SeriesActivityCandidate(series_id=series_id, name=series_names[series_id], completed_entries=count)
            for series_id, count in ranked
        ],
        next_unread=next_unread[:limit],
    )


@dataclass(frozen=True)
class _CompletedBook:
    book: Book
    completed_on: date | None


def _ranked_values(counts: Counter[str], limit: int) -> list[RankedValue]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return [RankedValue(label=label, count=count) for label, count in ranked[:limit]]


def _analytics_books(db: Session, *, user_id: int) -> list[Book]:
    return list(
        db.scalars(
            select(Book)
            .where(Book.user_id == user_id, Book.archived_at.is_(None))
            .options(selectinload(Book.reading_events), selectinload(Book.progress), selectinload(Book.genre_entries))
        ).all()
    )


def _analytics_series(db: Session, *, user_id: int) -> list[Series]:
    return list(
        db.scalars(
            select(Series)
            .where(Series.user_id == user_id)
            .options(
                selectinload(Series.books)
                .selectinload(SeriesBook.book)
                .selectinload(Book.reading_events),
                selectinload(Series.books).selectinload(SeriesBook.book).selectinload(Book.progress),
            )
            .order_by(Series.name.asc())
        ).all()
    )


def _unique_completed_books(db: Session, *, user_id: int, period: PeriodRange) -> list[_CompletedBook]:
    completed: list[_CompletedBook] = []
    for book in _analytics_books(db, user_id=user_id):
        completed_dates = _completion_dates(book)
        matching_dates = [value for value in completed_dates if period.contains(value)]
        if matching_dates:
            completed.append(_CompletedBook(book=book, completed_on=min(matching_dates)))
        elif not completed_dates and period.start is None and period.end is None and _has_undated_completion_evidence(book):
            completed.append(_CompletedBook(book=book, completed_on=None))
    return completed


def _completion_dates(book: Book) -> list[date]:
    events = sorted(
        (event for event in book.reading_events if event.event_type in COMPLETION_EVENT_TYPES),
        key=lambda event: event.event_date,
    )
    if events:
        return [event.event_date.date() for event in events]
    if book.completed_on is not None:
        return [book.completed_on]
    if book.status == "completed" and _current_progress_percent(book) is not None and _current_progress_percent(book) >= COMPLETION_PROGRESS_THRESHOLD:
        if book.progress is not None and book.progress.observed_at is not None:
            return [book.progress.observed_at.date()]
    return []


def _has_undated_completion_evidence(book: Book) -> bool:
    return book.status == "completed" or (_current_progress_percent(book) is not None and _current_progress_percent(book) >= COMPLETION_PROGRESS_THRESHOLD)


def _current_progress_percent(book: Book) -> float | None:
    if book.manual_progress_percent is not None:
        return book.manual_progress_percent
    if book.progress is not None:
        return book.progress.progress_percent
    return None


def _completion_events_by_book(db: Session, *, user_id: int) -> dict[Book, list[ReadingEvent]]:
    grouped: dict[Book, list[ReadingEvent]] = defaultdict(list)
    for book in _analytics_books(db, user_id=user_id):
        events = sorted(
            (event for event in book.reading_events if event.event_type in COMPLETION_EVENT_TYPES),
            key=lambda event: event.event_date,
        )
        if events:
            grouped[book] = events
    return grouped


def _likely_libby_relistens(book: Book, *, period: PeriodRange) -> int:
    if book.format != "audiobook" or book.progress is None or book.progress.enjoyed_seconds is None:
        return 0
    duration = book.audio_seconds or book.progress.total_seconds
    if duration is None or duration <= 0:
        return 0
    borrowed_events = sorted(
        (event for event in book.reading_events if event.source == "libby" and event.event_type == "borrowed"),
        key=lambda event: event.event_date,
    )
    if len(borrowed_events) < 2:
        return 0
    likely_consumptions = int(book.progress.enjoyed_seconds // (duration * COMPLETION_PROGRESS_THRESHOLD / 100))
    likely_repeats = max(0, min(len(borrowed_events) - 1, likely_consumptions - 1))
    confirmed_repeats = max(0, len([event for event in book.reading_events if event.event_type in COMPLETION_EVENT_TYPES]) - 1)
    likely_repeats = max(0, likely_repeats - confirmed_repeats)
    repeat_borrow_dates = [event.event_date.date() for event in borrowed_events[1 : 1 + likely_repeats]]
    return sum(1 for borrowed_on in repeat_borrow_dates if period.contains(borrowed_on))


def _next_unread_series_entry(series: Series) -> SeriesNextUnread | None:
    for entry in sorted(series.books, key=lambda item: (item.position is None, item.position or 0, item.id)):
        if entry.book is None:
            if entry.planned_title:
                return SeriesNextUnread(
                    series_id=series.id,
                    series_name=series.name,
                    title=entry.planned_title,
                    position=entry.position,
                )
            continue
        if not _completion_dates(entry.book):
            return SeriesNextUnread(
                series_id=series.id,
                series_name=series.name,
                title=entry.book.title,
                position=entry.position,
            )
    return None
