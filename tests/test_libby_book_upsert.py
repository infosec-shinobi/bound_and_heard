from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.importers.libby_json import parse_libby_export
from app.models import Book, User
from app.services.import_service import upsert_libby_book


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
    db.commit()


def libby_item(
    *,
    title: str = "A Sample Book",
    author: str = "Example Author",
    title_id: str = "12345",
    book_format: str = "audiobook",
    isbn: str = "9781234567890",
):
    return parse_libby_export(
        {
            "version": 1,
            "timeline": [
                {
                    "cover": {
                        "contentType": "image/jpeg",
                        "url": "https://example.test/cover.jpg",
                        "title": title,
                        "color": "#123456",
                        "format": book_format,
                    },
                    "title": {
                        "text": title,
                        "url": f"https://share.libbyapp.com/title/{title_id}",
                        "titleId": title_id,
                    },
                    "author": author,
                    "publisher": "Example Publisher",
                    "isbn": isbn,
                    "timestamp": 1767903363000,
                    "activity": "Borrowed",
                    "details": " 21 days ",
                    "library": {"text": "Example Library", "key": "examplelibrary"},
                }
            ],
        }
    ).timeline[0]


def test_upsert_libby_book_creates_book_when_no_match_exists() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        result = upsert_libby_book(db, user_id=DEFAULT_LOCAL_USER_ID, item=libby_item())
        db.commit()
        book = db.query(Book).one()

    assert result.created is True
    assert result.updated is False
    assert book.title == "A Sample Book"
    assert book.primary_author_name == "Example Author"
    assert book.publisher == "Example Publisher"
    assert book.isbn13 == "9781234567890"
    assert book.libby_title_id == "12345"
    assert book.libby_share_url == "https://share.libbyapp.com/title/12345"
    assert book.format == "audiobook"
    assert book.status == "borrowed"
    assert book.cover_url == "https://example.test/cover.jpg"
    assert book.cover_color == "#123456"
    assert book.title_source == "libby"
    assert book.author_source == "libby"
    assert book.metadata_source == "libby"


def test_upsert_libby_book_matches_existing_book_by_libby_title_id() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        existing = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Manual Title",
            format="audiobook",
            status="started",
            libby_title_id="12345",
            notes="Keep notes.",
            rating=5,
            manual_progress_percent=40,
        )
        db.add(existing)
        db.commit()

        result = upsert_libby_book(db, user_id=DEFAULT_LOCAL_USER_ID, item=libby_item())
        db.commit()
        books = db.query(Book).all()

    assert result.created is False
    assert result.updated is True
    assert len(books) == 1
    assert books[0].title == "Manual Title"
    assert books[0].notes == "Keep notes."
    assert books[0].rating == 5
    assert books[0].manual_progress_percent == 40
    assert books[0].primary_author_name == "Example Author"
    assert books[0].publisher == "Example Publisher"
    assert books[0].libby_share_url == "https://share.libbyapp.com/title/12345"


def test_upsert_libby_book_uses_exact_title_author_format_fallback() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        existing = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="a sample book",
            primary_author_name="example author",
            format="audiobook",
            status="unknown",
        )
        db.add(existing)
        db.commit()

        result = upsert_libby_book(db, user_id=DEFAULT_LOCAL_USER_ID, item=libby_item())
        db.commit()
        books = db.query(Book).all()

    assert result.created is False
    assert result.updated is True
    assert len(books) == 1
    assert books[0].libby_title_id == "12345"
    assert books[0].libby_share_url == "https://share.libbyapp.com/title/12345"


def test_upsert_libby_book_does_not_use_fallback_when_format_differs() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        db.add(
            Book(
                user_id=DEFAULT_LOCAL_USER_ID,
                title="A Sample Book",
                primary_author_name="Example Author",
                format="ebook",
                status="unknown",
            )
        )
        db.commit()

        result = upsert_libby_book(db, user_id=DEFAULT_LOCAL_USER_ID, item=libby_item(book_format="audiobook"))
        db.commit()

        assert result.created is True
        assert db.query(Book).count() == 2


def test_upsert_libby_book_fills_only_empty_fields_on_existing_book() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        existing = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Manual Title",
            primary_author_name="Manual Author",
            format="unknown",
            status="completed",
            completed_on=date(2026, 1, 1),
            notes="Do not overwrite.",
            rating=4,
            manual_progress_percent=100,
            libby_title_id="12345",
        )
        db.add(existing)
        db.commit()

        result = upsert_libby_book(db, user_id=DEFAULT_LOCAL_USER_ID, item=libby_item())
        db.commit()
        book = db.query(Book).one()

    assert result.created is False
    assert result.updated is True
    assert book.title == "Manual Title"
    assert book.primary_author_name == "Manual Author"
    assert book.status == "completed"
    assert book.completed_on.isoformat() == "2026-01-01"
    assert book.notes == "Do not overwrite."
    assert book.rating == 4
    assert book.manual_progress_percent == 100
    assert book.format == "audiobook"
    assert book.publisher == "Example Publisher"
    assert book.isbn13 == "9781234567890"
    assert book.cover_url == "https://example.test/cover.jpg"
    assert book.author_source is None
    assert book.metadata_source == "libby"


def test_upsert_libby_book_tracks_source_when_filling_empty_imported_metadata() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        existing = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Manual Title",
            format="unknown",
            status="unknown",
            libby_title_id="12345",
            title_source="manual",
        )
        db.add(existing)
        db.commit()

        result = upsert_libby_book(db, user_id=DEFAULT_LOCAL_USER_ID, item=libby_item())
        db.commit()
        book = db.query(Book).one()

    assert result.created is False
    assert result.updated is True
    assert book.title == "Manual Title"
    assert book.title_source == "manual"
    assert book.primary_author_name == "Example Author"
    assert book.author_source == "libby"
    assert book.publisher == "Example Publisher"
    assert book.metadata_source == "libby"


def test_upsert_libby_book_stores_isbn10_when_libby_isbn_is_ten_digits() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        upsert_libby_book(db, user_id=DEFAULT_LOCAL_USER_ID, item=libby_item(isbn="123456789X"))
        db.commit()
        book = db.query(Book).one()

    assert book.isbn10 == "123456789X"
    assert book.isbn13 is None
