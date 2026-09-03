from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, BookGenre, BookProgress, Genre, MetadataEnrichmentRun, ReadingEvent, Series, SeriesBook, User
from app.services.recap_service import (
    RecapAlreadyExistsError,
    export_recap_markdown,
    generate_quarterly_recap,
    generate_yearly_recap,
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
    page_count: int | None = None,
    audio_seconds: int | None = None,
) -> Book:
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=title,
        primary_author_name=author,
        format=book_format,
        page_count=page_count,
        audio_seconds=audio_seconds,
    )
    db.add(book)
    db.flush()
    return book


def add_completion_event(db: Session, book: Book, when: date) -> None:
    db.add(
        ReadingEvent(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source="manual",
            source_event_id=f"{book.id}:completed:{when.isoformat()}",
            event_type="completed",
            event_date=datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc),
            progress_percent=100,
        )
    )
    db.flush()


def add_genre(db: Session, book: Book, name: str) -> None:
    genre = Genre(user_id=DEFAULT_LOCAL_USER_ID, name=name, normalized_name=name.casefold(), source="manual")
    db.add(genre)
    db.flush()
    db.add(BookGenre(user_id=DEFAULT_LOCAL_USER_ID, book_id=book.id, genre_id=genre.id, source="manual"))
    db.flush()


def seed_recap_data(db: Session) -> None:
    ebook = add_book(db, title="Quarter Ebook", author="Alice", book_format="ebook", page_count=300)
    audio = add_book(db, title="Quarter Audio", author="Bob", book_format="audiobook", audio_seconds=7200)
    old = add_book(db, title="Old Book", author="Cara", book_format="ebook", page_count=500)
    add_completion_event(db, ebook, date(2026, 4, 10))
    add_completion_event(db, audio, date(2026, 5, 10))
    add_completion_event(db, old, date(2025, 1, 1))
    add_genre(db, ebook, "Sci Fi")
    add_genre(db, audio, "Mystery")
    series = Series(user_id=DEFAULT_LOCAL_USER_ID, name="Recap Saga", status="active", wants_to_continue="yes")
    db.add(series)
    db.flush()
    db.add(SeriesBook(series_id=series.id, book_id=ebook.id, position=1))
    db.add(SeriesBook(series_id=series.id, book_id=audio.id, position=2))


def test_generate_quarterly_recap_persists_metadata_payload_and_artifact(tmp_path: Path) -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        seed_recap_data(db)
        db.commit()

        recap = generate_quarterly_recap(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            year=2026,
            quarter=2,
            output_dir=tmp_path,
        )
        db.commit()

        assert recap.period_type == "quarter"
        assert recap.year == 2026
        assert recap.quarter == 2
        assert recap.title == "Q2 2026 Recap"
        assert recap.summary == "Q2 2026 Recap: 2 completed book(s)."
        assert recap.payload["completed_count"] == 2
        assert recap.payload["format_breakdown"] == {"audiobook": 1, "ebook": 1}
        assert recap.payload["favorite_authors"][0] == {"label": "Alice", "count": 1}
        assert recap.payload["favorite_genres"][0] == {"label": "Mystery", "count": 1}
        assert recap.payload["favorite_series"] == [{"id": 1, "name": "Recap Saga", "completed_entries": 2}]
        assert recap.payload["longest_book"] == {
            "id": 2,
            "title": "Quarter Audio",
            "author": "Bob",
            "metric": "seconds",
            "value": 7200,
        }
        output_path = Path(recap.output_path)
        assert output_path == tmp_path / "quarter" / "2026-q2.json"
        assert json.loads(output_path.read_text(encoding="utf-8")) == recap.payload


def test_generate_yearly_recap_uses_quarter_zero_and_is_deterministic(tmp_path: Path) -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        seed_recap_data(db)
        db.commit()

        recap = generate_yearly_recap(db, user_id=DEFAULT_LOCAL_USER_ID, year=2026, output_dir=tmp_path)
        first_payload = recap.payload
        first_artifact = Path(recap.output_path).read_text(encoding="utf-8")

        with pytest.raises(RecapAlreadyExistsError):
            generate_yearly_recap(db, user_id=DEFAULT_LOCAL_USER_ID, year=2026, output_dir=tmp_path)

        overwritten = generate_yearly_recap(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            year=2026,
            output_dir=tmp_path,
            overwrite=True,
        )

        assert overwritten.id == recap.id
        assert overwritten.period_type == "year"
        assert overwritten.quarter == 0
        assert overwritten.payload == first_payload
        assert Path(overwritten.output_path).read_text(encoding="utf-8") == first_artifact


def test_export_recap_markdown_writes_metadata_and_metrics(tmp_path: Path) -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        seed_recap_data(db)
        db.commit()
        recap = generate_quarterly_recap(db, user_id=DEFAULT_LOCAL_USER_ID, year=2026, quarter=2, output_dir=tmp_path)
        db.commit()

        output_path = Path(export_recap_markdown(recap, output_dir=tmp_path / "exports"))

        assert output_path == tmp_path / "exports" / "recaps" / "quarter" / "2026-q2.md"
        content = output_path.read_text(encoding="utf-8")
        assert "# Q2 2026 Recap" in content
        assert "Period: Q2 2026" in content
        assert "Generated:" in content
        assert "Source artifact:" in content
        assert "- Books completed: 2" in content
        assert "- Favorite series: Recap Saga" in content


def test_generate_recap_preserves_source_data_and_only_adds_recap(tmp_path: Path) -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = add_book(db, title="Preserved Libby", author="Author", book_format="audiobook", audio_seconds=3600)
        libby_event = ReadingEvent(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source="libby",
            source_event_id="libby-preserved-borrow",
            event_type="borrowed",
            event_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
            raw_data={"library": "test"},
        )
        completed_event = ReadingEvent(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source="libby",
            source_event_id="libby-preserved-completed",
            event_type="completed",
            event_date=datetime(2026, 4, 15, tzinfo=timezone.utc),
            progress_percent=100,
            raw_data={"activity": "Completed"},
        )
        progress = BookProgress(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source="scraped",
            progress_percent=100,
            position_seconds=3600,
            enjoyed_seconds=3600,
        )
        enrichment = MetadataEnrichmentRun(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            provider="open_library",
            lookup_type="title_author",
            normalized_query="preserved libby author",
            status="succeeded",
            fields_applied={"page_count": {"from": None, "to": 123}},
        )
        series = Series(user_id=DEFAULT_LOCAL_USER_ID, name="Preserved Series", status="active", wants_to_continue="yes")
        db.add_all([libby_event, completed_event, progress, enrichment, series])
        db.flush()
        assignment = SeriesBook(series_id=series.id, book_id=book.id, position=1)
        db.add(assignment)
        db.commit()

        before = {
            "book": (book.title, book.primary_author_name, book.audio_seconds, book.status),
            "events": [
                (event.source, event.source_event_id, event.event_type, event.event_date, event.progress_percent, event.raw_data)
                for event in db.query(ReadingEvent).order_by(ReadingEvent.id).all()
            ],
            "progress": (
                progress.source,
                progress.progress_percent,
                progress.position_seconds,
                progress.enjoyed_seconds,
            ),
            "enrichment": (
                enrichment.provider,
                enrichment.lookup_type,
                enrichment.normalized_query,
                enrichment.status,
                enrichment.fields_applied,
            ),
            "series_assignment": (assignment.series_id, assignment.book_id, assignment.position, assignment.position_end),
        }

        generate_quarterly_recap(db, user_id=DEFAULT_LOCAL_USER_ID, year=2026, quarter=2, output_dir=tmp_path)
        db.commit()

        db.refresh(book)
        db.refresh(progress)
        db.refresh(enrichment)
        db.refresh(assignment)
        after = {
            "book": (book.title, book.primary_author_name, book.audio_seconds, book.status),
            "events": [
                (event.source, event.source_event_id, event.event_type, event.event_date, event.progress_percent, event.raw_data)
                for event in db.query(ReadingEvent).order_by(ReadingEvent.id).all()
            ],
            "progress": (
                progress.source,
                progress.progress_percent,
                progress.position_seconds,
                progress.enjoyed_seconds,
            ),
            "enrichment": (
                enrichment.provider,
                enrichment.lookup_type,
                enrichment.normalized_query,
                enrichment.status,
                enrichment.fields_applied,
            ),
            "series_assignment": (assignment.series_id, assignment.book_id, assignment.position, assignment.position_end),
        }

        assert after == before
