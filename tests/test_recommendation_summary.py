from __future__ import annotations

from datetime import date, datetime, timezone
import json

from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, BookGenre, BookProgress, Genre, ReadingEvent, Series, SeriesBook, User
from app.services.analytics import year_range
from app.services.recommendation_summary import summarize_reading_history


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
    author: str,
    book_format: str,
    status: str = "completed",
    rating: float | None = None,
    page_count: int | None = None,
    audio_seconds: int | None = None,
    notes: str | None = None,
) -> Book:
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=title,
        primary_author_name=author,
        format=book_format,
        status=status,
        rating=rating,
        page_count=page_count,
        audio_seconds=audio_seconds,
        notes=notes,
    )
    db.add(book)
    db.flush()
    return book


def add_completion(db: Session, book: Book, when: date) -> None:
    db.add(
        ReadingEvent(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source="manual",
            event_type="completed",
            event_date=datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc),
            raw_data={"private_raw_payload": "should-not-appear"},
        )
    )
    db.flush()


def add_genre(db: Session, book: Book, name: str) -> None:
    genre = db.scalars(
        select(Genre).where(Genre.user_id == DEFAULT_LOCAL_USER_ID, Genre.normalized_name == name.casefold())
    ).one_or_none()
    if genre is None:
        genre = Genre(user_id=DEFAULT_LOCAL_USER_ID, name=name, normalized_name=name.casefold(), source="manual")
        db.add(genre)
        db.flush()
    db.add(BookGenre(user_id=DEFAULT_LOCAL_USER_ID, book_id=book.id, genre_id=genre.id, source="manual"))
    db.flush()


def test_summarize_reading_history_includes_analytics_recent_items_and_series_context() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        completed = add_book(
            db,
            title="Completed Fantasy",
            author="Favorite Author",
            book_format="ebook",
            rating=4.5,
            page_count=320,
            notes="Loved the found family arc, but this full note should stay out by default.",
        )
        audio = add_book(
            db,
            title="Completed Audio",
            author="Favorite Author",
            book_format="audiobook",
            rating=5,
            audio_seconds=36_000,
        )
        abandoned = add_book(db, title="Abandoned Book", author="Other Author", book_format="ebook", status="abandoned")
        next_book = add_book(db, title="Next Owned Book", author="Favorite Author", book_format="ebook", status="want_to_read")
        add_completion(db, completed, date(2026, 1, 10))
        add_completion(db, audio, date(2026, 2, 15))
        add_genre(db, completed, "Fantasy")
        add_genre(db, audio, "Fantasy")
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=abandoned.id,
                source="manual",
                event_type="abandoned",
                event_date=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
                raw_data={"raw_libby_html": "<html>private</html>"},
            )
        )
        db.add(BookProgress(user_id=DEFAULT_LOCAL_USER_ID, book_id=abandoned.id, source="manual", progress_percent=42))
        series = Series(user_id=DEFAULT_LOCAL_USER_ID, name="Favorite Series", status="active", wants_to_continue="yes")
        db.add(series)
        db.flush()
        db.add_all(
            [
                SeriesBook(series_id=series.id, book_id=completed.id, position=1),
                SeriesBook(series_id=series.id, book_id=next_book.id, position=2),
                SeriesBook(series_id=series.id, planned_title="Planned Finale", planned_author_name="Favorite Author", planned_format="ebook", position=3),
            ]
        )
        db.commit()

        summary = summarize_reading_history(db, user_id=DEFAULT_LOCAL_USER_ID, period=year_range(2026))

    assert summary["period"] == {"start": "2026-01-01", "end": "2026-12-31"}
    assert summary["totals"]["completed_books"] == 2
    assert summary["totals"]["pages_read"] == 320
    assert summary["totals"]["audiobook_seconds"] == 36_000
    assert summary["favorites"]["authors"] == [{"label": "Favorite Author", "count": 2}]
    assert summary["favorites"]["genres"] == [{"label": "Fantasy", "count": 2}]
    assert {row["format"]: row["count"] for row in summary["favorites"]["formats"]} == {"audiobook": 1, "ebook": 1}
    assert summary["preferences"]["average_rating"] == 4.75
    assert summary["preferences"]["typical_page_count"] == 320
    assert summary["preferences"]["typical_audiobook_seconds"] == 36_000
    assert [row["title"] for row in summary["recent"]["completed"]] == ["Completed Audio", "Completed Fantasy"]
    assert summary["recent"]["abandoned"][0]["title"] == "Abandoned Book"
    assert summary["recent"]["abandoned"][0]["progress_percent"] == 42
    assert summary["series"]["next_unread"][0]["title"] == "Next Owned Book"
    assert summary["series"]["planned_unread"][0]["title"] == "Planned Finale"


def test_summarize_reading_history_excludes_private_raw_data_and_notes_by_default() -> None:
    session_factory = make_session_factory()
    secret_values = [
        "BOUND_AND_HEARD_SESSION_SECRET",
        "admin-password-value",
        "data/browser/libby-profile/Cookies",
        "data/scraped/libby/job-1/item-1/private.html",
        "<html>private libby journey</html>",
        "raw import payload",
        "This is a very private note",
    ]
    with session_factory() as db:
        add_user(db)
        book = add_book(
            db,
            title="Privacy Book",
            author="Private Author",
            book_format="ebook",
            notes="This is a very private note",
        )
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="libby",
                event_type="completed",
                event_date=datetime(2026, 4, 1, 12, tzinfo=timezone.utc),
                raw_data={"secrets": secret_values},
            )
        )
        db.commit()

        summary = summarize_reading_history(db, user_id=DEFAULT_LOCAL_USER_ID)

    encoded = json.dumps(summary, sort_keys=True)
    for value in secret_values:
        assert value not in encoded
    assert summary["safety"] == {
        "raw_import_files_included": False,
        "raw_scrape_snapshots_included": False,
        "browser_profile_included": False,
        "secrets_included": False,
        "raw_provider_responses_included": False,
        "full_notes_included": False,
    }
    assert "note_summaries" not in summary


def test_summarize_reading_history_can_include_bounded_note_excerpts_when_enabled() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = add_book(
            db,
            title="Noted Book",
            author="Note Author",
            book_format="ebook",
            notes="Loved the prose and disliked the pacing. " * 20,
        )
        add_completion(db, book, date(2026, 5, 5))
        db.commit()

        summary = summarize_reading_history(db, user_id=DEFAULT_LOCAL_USER_ID, include_note_summaries=True)

    assert summary["safety"]["full_notes_included"] is True
    assert summary["note_summaries"][0]["title"] == "Noted Book"
    assert len(summary["note_summaries"][0]["note_excerpt"]) == 200
