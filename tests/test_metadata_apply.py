from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, BookGenre, BookProgress, Genre, MetadataEnrichmentRun, ReadingEvent, Series, SeriesBook, User
from app.services.metadata_apply import apply_metadata_result_to_empty_fields
from app.services.metadata_providers import MetadataResult


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


def enrichment_result() -> MetadataResult:
    return MetadataResult(
        provider="google_books",
        title="Provider Title",
        subtitle="Provider Subtitle",
        authors=("Provider Author",),
        publisher="Provider Press",
        published_on=date(2020, 5, 4),
        publication_year=2020,
        isbn10="123456789X",
        isbn13="9781234567890",
        page_count=321,
        cover_url="https://example.test/cover.jpg",
        categories=("Science Fiction", "science fiction", "Fantasy / Epic"),
        confidence=0.98,
    )


def test_apply_metadata_result_fills_only_supported_empty_fields_and_records_run() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Manual Title", primary_author_name="Manual Author", format="ebook", status="unknown")
        db.add(book)
        db.flush()

        applied = apply_metadata_result_to_empty_fields(
            db,
            book=book,
            result=enrichment_result(),
            cache_entry_id=12,
            lookup_type="isbn",
            normalized_query="9781234567890",
        )

        assert applied.updated is True
        assert book.title == "Manual Title"
        assert book.primary_author_name == "Manual Author"
        assert book.subtitle == "Provider Subtitle"
        assert book.publisher == "Provider Press"
        assert book.published_on == date(2020, 5, 4)
        assert book.publication_year == 2020
        assert book.isbn10 == "123456789X"
        assert book.isbn13 == "9781234567890"
        assert book.page_count == 321
        assert book.cover_url == "https://example.test/cover.jpg"
        assert book.metadata_source == "google_books"
        assert [entry.genre.name for entry in book.genre_entries] == ["Science Fiction", "Fantasy / Epic"]
        assert book.genre_entries[0].source == "google_books"
        assert book.genre_entries[0].raw_label == "Science Fiction"
        assert applied.run.status == "completed"
        assert applied.run.fields_applied["page_count"] == {"source": "google_books", "value": 321}
        assert applied.run.fields_applied["genres"] == {
            "source": "google_books",
            "value": [
                {"name": "Science Fiction", "raw_label": "Science Fiction"},
                {"name": "Fantasy / Epic", "raw_label": "Fantasy / Epic"},
            ],
        }
        assert applied.run.lookup_type == "isbn"
        assert applied.run.normalized_query == "9781234567890"


def test_apply_metadata_result_preserves_existing_values_and_libby_attribution() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Manual Title",
            primary_author_name="Manual Author",
            subtitle="Manual Subtitle",
            publisher="Manual Press",
            published_on=date(1999, 1, 1),
            publication_year=1999,
            isbn10="1111111111",
            isbn13="9781111111111",
            page_count=111,
            cover_url="https://example.test/manual.jpg",
            metadata_source="libby",
            format="ebook",
            status="completed",
            rating=5,
            notes="manual note",
            completed_on=date(2024, 1, 1),
        )
        db.add(book)
        db.flush()

        applied = apply_metadata_result_to_empty_fields(
            db,
            book=book,
            result=MetadataResult(
                provider="google_books",
                title="Provider Title",
                publisher="Provider Press",
                published_on=date(2020, 5, 4),
                publication_year=2020,
                isbn10="123456789X",
                isbn13="9781234567890",
                page_count=321,
                cover_url="https://example.test/cover.jpg",
                confidence=0.98,
            ),
        )

        assert applied.updated is False
        assert book.title == "Manual Title"
        assert book.primary_author_name == "Manual Author"
        assert book.subtitle == "Manual Subtitle"
        assert book.publisher == "Manual Press"
        assert book.publication_year == 1999
        assert book.isbn13 == "9781111111111"
        assert book.page_count == 111
        assert book.cover_url == "https://example.test/manual.jpg"
        assert book.metadata_source == "libby"
        assert book.status == "completed"
        assert book.rating == 5
        assert book.notes == "manual note"
        assert book.completed_on == date(2024, 1, 1)
        assert applied.run.status == "skipped"
        assert applied.run.fields_applied == {}


def test_apply_metadata_result_does_not_touch_progress_events_or_series_assignments() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Manual Title", primary_author_name="Manual Author", format="ebook", status="unknown")
        db.add(book)
        db.flush()
        progress = BookProgress(user_id=DEFAULT_LOCAL_USER_ID, book_id=book.id, source="libby", progress_percent=50)
        event = ReadingEvent(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source="libby",
            event_type="progress_seen",
            event_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        series = Series(user_id=DEFAULT_LOCAL_USER_ID, name="Manual Series")
        db.add_all([progress, event, series])
        db.flush()
        series_book = SeriesBook(series_id=series.id, book_id=book.id, position=1)
        db.add(series_book)
        db.flush()

        apply_metadata_result_to_empty_fields(db, book=book, result=enrichment_result())

        assert db.get(BookProgress, progress.id).progress_percent == 50
        assert db.get(ReadingEvent, event.id).event_type == "progress_seen"
        assert db.get(SeriesBook, series_book.id).book_id == book.id
        assert db.scalar(select(MetadataEnrichmentRun).where(MetadataEnrichmentRun.book_id == book.id)) is not None


def test_apply_metadata_result_reuses_existing_genre_and_preserves_manual_book_genre() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Manual Genre Book", format="ebook", status="unknown")
        genre = Genre(user_id=DEFAULT_LOCAL_USER_ID, name="Sci Fi", normalized_name="sci fi", source="manual")
        db.add_all([book, genre])
        db.flush()
        manual_entry = BookGenre(user_id=DEFAULT_LOCAL_USER_ID, book_id=book.id, genre_id=genre.id, source="manual", raw_label=None)
        db.add(manual_entry)
        db.flush()

        result = MetadataResult(
            provider="google_books",
            title="Manual Genre Book",
            categories=("SCI FI", "Mystery"),
            confidence=0.9,
        )
        applied = apply_metadata_result_to_empty_fields(db, book=book, result=result)

        genres = db.query(Genre).order_by(Genre.name).all()
        assert [(genre.name, genre.normalized_name, genre.source) for genre in genres] == [
            ("Mystery", "mystery", "google_books"),
            ("Sci Fi", "sci fi", "manual"),
        ]
        entries = db.query(BookGenre).join(Genre).order_by(Genre.name).all()
        assert [(entry.genre.name, entry.source, entry.raw_label) for entry in entries] == [
            ("Mystery", "google_books", "Mystery"),
            ("Sci Fi", "manual", None),
        ]
        assert applied.fields_applied["genres"] == {
            "source": "google_books",
            "value": [{"name": "Mystery", "raw_label": "Mystery"}],
        }
