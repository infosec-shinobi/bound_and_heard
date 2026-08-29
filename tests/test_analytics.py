from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, BookGenre, BookProgress, Genre, ReadingEvent, User
from app.services.analytics import (
    audiobook_seconds,
    books_completed_by_month,
    books_completed_by_period,
    format_breakdown,
    lifetime_enjoyed_seconds,
    month_range,
    pages_read,
    partial_progress_summary,
    quarter_range,
    repeat_counts,
    top_authors,
    top_genres,
    year_range,
)


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_user(db: Session) -> None:
    db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
    db.flush()


def add_book(
    db: Session,
    *,
    title: str,
    author: str = "Author",
    book_format: str = "ebook",
    status: str = "unknown",
    completed_on: date | None = None,
    page_count: int | None = None,
    audio_seconds: int | None = None,
    manual_progress_percent: float | None = None,
) -> Book:
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=title,
        primary_author_name=author,
        format=book_format,
        status=status,
        completed_on=completed_on,
        page_count=page_count,
        audio_seconds=audio_seconds,
        manual_progress_percent=manual_progress_percent,
    )
    db.add(book)
    db.flush()
    return book


def add_completion_event(db: Session, book: Book, when: date, *, event_type: str = "completed") -> ReadingEvent:
    event = ReadingEvent(
        user_id=book.user_id,
        book_id=book.id,
        source="manual" if event_type == "manually_completed" else "libby",
        source_event_id=f"{book.id}:{event_type}:{when.isoformat()}",
        event_type=event_type,
        event_date=datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc),
        progress_percent=100,
    )
    db.add(event)
    db.flush()
    return event


def add_borrowed_event(db: Session, book: Book, when: date) -> ReadingEvent:
    event = ReadingEvent(
        user_id=book.user_id,
        book_id=book.id,
        source="libby",
        source_event_id=f"{book.id}:borrowed:{when.isoformat()}",
        event_type="borrowed",
        event_date=datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc),
    )
    db.add(event)
    db.flush()
    return event


def add_genre(db: Session, book: Book, name: str) -> None:
    genre = db.query(Genre).filter_by(user_id=book.user_id, normalized_name=name.casefold()).first()
    if genre is None:
        genre = Genre(user_id=book.user_id, name=name, normalized_name=name.casefold(), source="manual")
        db.add(genre)
        db.flush()
    db.add(BookGenre(user_id=book.user_id, book_id=book.id, genre_id=genre.id, source="manual"))
    db.flush()


def test_period_range_helpers_are_inclusive() -> None:
    assert month_range(2026, 2).start == date(2026, 2, 1)
    assert month_range(2026, 2).end == date(2026, 2, 28)
    assert month_range(2024, 2).end == date(2024, 2, 29)
    assert quarter_range(2026, 2).start == date(2026, 4, 1)
    assert quarter_range(2026, 2).end == date(2026, 6, 30)
    assert year_range(2026).contains(date(2026, 12, 31)) is True
    assert year_range(2026).contains(date(2027, 1, 1)) is False


def test_completed_books_by_month_uses_completion_events_before_book_date() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        event_book = add_book(db, title="Event Book", completed_on=date(2026, 8, 1))
        add_completion_event(db, event_book, date(2026, 7, 31))
        fallback_book = add_book(db, title="Fallback Book", completed_on=date(2026, 8, 2))
        archived_book = add_book(db, title="Archived Book", completed_on=date(2026, 8, 3))
        archived_book.archived_at = datetime(2026, 8, 4, tzinfo=timezone.utc)
        db.commit()

        counts = books_completed_by_month(db, user_id=DEFAULT_LOCAL_USER_ID, year=2026)

        assert [(count.year, count.month, count.count) for count in counts] == [(2026, 7, 1), (2026, 8, 1)]
        assert books_completed_by_period(db, user_id=DEFAULT_LOCAL_USER_ID, period=month_range(2026, 8)) == 1
        assert fallback_book.id is not None


def test_format_author_genre_page_and_audio_aggregates() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        ebook = add_book(db, title="Ebook", author="Alice", book_format="ebook", page_count=300)
        physical = add_book(db, title="Physical", author="Alice", book_format="physical", page_count=200)
        audio = add_book(db, title="Audio", author="Bob", book_format="audiobook", audio_seconds=7200)
        for book in (ebook, physical, audio):
            add_completion_event(db, book, date(2026, 1, 15))
        add_genre(db, ebook, "Sci Fi")
        add_genre(db, physical, "Sci Fi")
        add_genre(db, audio, "Mystery")
        db.commit()

        period = year_range(2026)

        assert format_breakdown(db, user_id=DEFAULT_LOCAL_USER_ID, period=period) == {
            "audiobook": 1,
            "ebook": 1,
            "physical": 1,
        }
        assert [(value.label, value.count) for value in top_authors(db, user_id=DEFAULT_LOCAL_USER_ID, period=period)] == [
            ("Alice", 2),
            ("Bob", 1),
        ]
        assert [(value.label, value.count) for value in top_genres(db, user_id=DEFAULT_LOCAL_USER_ID, period=period)] == [
            ("Sci Fi", 2),
            ("Mystery", 1),
        ]
        assert pages_read(db, user_id=DEFAULT_LOCAL_USER_ID, period=period) == 500
        assert audiobook_seconds(db, user_id=DEFAULT_LOCAL_USER_ID, period=period) == 7200


def test_audiobook_seconds_can_use_progress_total_when_book_duration_missing() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        audio = add_book(db, title="Audio", book_format="audiobook")
        add_completion_event(db, audio, date(2026, 1, 15))
        db.add(BookProgress(user_id=audio.user_id, book_id=audio.id, source="scraped", total_seconds=3600))
        db.commit()

        assert audiobook_seconds(db, user_id=DEFAULT_LOCAL_USER_ID, period=year_range(2026)) == 3600


def test_lifetime_enjoyed_seconds_prefers_scraped_enjoyed_time_and_counts_manual_audio_completions() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        scraped = add_book(db, title="Scraped Audio", book_format="audiobook", audio_seconds=7200)
        db.add(
            BookProgress(
                user_id=scraped.user_id,
                book_id=scraped.id,
                source="scraped",
                enjoyed_seconds=9000,
                read_count=12,
            )
        )
        manual = add_book(db, title="Manual Audio", book_format="audiobook", audio_seconds=3600)
        add_completion_event(db, manual, date(2025, 1, 1), event_type="manually_completed")
        add_completion_event(db, manual, date(2026, 1, 1), event_type="manually_completed")
        ebook = add_book(db, title="Manual Ebook", book_format="ebook", audio_seconds=9999)
        add_completion_event(db, ebook, date(2026, 1, 1), event_type="manually_completed")
        db.commit()

        assert lifetime_enjoyed_seconds(db, user_id=DEFAULT_LOCAL_USER_ID) == 16200


def test_partial_progress_summary_uses_manual_progress_before_scraped_progress() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        ebook = add_book(
            db,
            title="Started Ebook",
            book_format="ebook",
            status="started",
            page_count=200,
            manual_progress_percent=25,
        )
        db.add(BookProgress(user_id=ebook.user_id, book_id=ebook.id, source="scraped", progress_percent=75))
        audio = add_book(db, title="Abandoned Audio", book_format="audiobook", status="abandoned", audio_seconds=7200)
        db.add(BookProgress(user_id=audio.user_id, book_id=audio.id, source="scraped", progress_percent=50))
        completed = add_book(db, title="Complete", status="completed", manual_progress_percent=98)
        db.commit()

        summary = partial_progress_summary(db, user_id=DEFAULT_LOCAL_USER_ID)

        assert summary.book_count == 2
        assert summary.abandoned_count == 1
        assert summary.average_progress_percent == 37.5
        assert summary.pages_in_progress == 50
        assert summary.audiobook_seconds_in_progress == 3600
        assert completed.id is not None


def test_repeat_counts_are_derived_from_completion_events_only() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        ebook = add_book(db, title="Reread", book_format="ebook")
        audio = add_book(db, title="Relisten", book_format="audiobook")
        unknown = add_book(db, title="Unknown Repeat", book_format="unknown")
        add_completion_event(db, ebook, date(2025, 1, 1))
        add_completion_event(db, ebook, date(2026, 1, 1))
        add_completion_event(db, audio, date(2025, 2, 1))
        add_completion_event(db, audio, date(2026, 2, 1))
        add_completion_event(db, unknown, date(2025, 3, 1))
        add_completion_event(db, unknown, date(2026, 3, 1))
        session_count_book = add_book(db, title="Session Count", book_format="audiobook")
        db.add(BookProgress(user_id=session_count_book.user_id, book_id=session_count_book.id, source="scraped", read_count=12))
        db.commit()

        counts = repeat_counts(db, user_id=DEFAULT_LOCAL_USER_ID, period=year_range(2026))

        assert counts.rereads == 1
        assert counts.relistens == 1
        assert counts.repeat_completions == 1


def test_repeat_counts_include_lower_confidence_likely_libby_relistens() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = add_book(db, title="Likely Relisten", book_format="audiobook", audio_seconds=3600)
        add_borrowed_event(db, book, date(2025, 1, 1))
        add_borrowed_event(db, book, date(2026, 1, 1))
        db.add(BookProgress(user_id=book.user_id, book_id=book.id, source="scraped", enjoyed_seconds=7200, read_count=12))
        db.commit()

        counts = repeat_counts(db, user_id=DEFAULT_LOCAL_USER_ID, period=year_range(2026))

        assert counts.relistens == 0
        assert counts.likely_relistens == 1


def test_repeat_counts_do_not_infer_repeats_from_picked_up_count_or_borrows_alone() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        picked_up = add_book(db, title="Picked Up", book_format="audiobook", audio_seconds=3600)
        add_borrowed_event(db, picked_up, date(2025, 1, 1))
        db.add(BookProgress(user_id=picked_up.user_id, book_id=picked_up.id, source="scraped", read_count=12))
        borrowed = add_book(db, title="Borrowed Twice", book_format="audiobook", audio_seconds=3600)
        add_borrowed_event(db, borrowed, date(2025, 1, 1))
        add_borrowed_event(db, borrowed, date(2026, 1, 1))
        db.add(BookProgress(user_id=borrowed.user_id, book_id=borrowed.id, source="scraped", enjoyed_seconds=1800))
        db.commit()

        counts = repeat_counts(db, user_id=DEFAULT_LOCAL_USER_ID, period=year_range(2026))

        assert counts.relistens == 0
        assert counts.likely_relistens == 0


def test_prior_manual_completion_entries_count_as_completed_books() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = add_book(db, title="Prior Book", book_format="ebook")
        add_completion_event(db, book, date(2020, 1, 1), event_type="manually_completed")
        db.commit()

        assert books_completed_by_period(db, user_id=DEFAULT_LOCAL_USER_ID, period=year_range(2020)) == 1
