from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.importers.libby_json import parse_libby_export
from app.models import Book, ReadingEvent, User
from app.services.import_service import process_libby_timeline_items


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_manual_book_with_correction_event(db: Session) -> Book:
    db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title="Manual Title",
        primary_author_name="Manual Author",
        publisher="Manual Publisher",
        isbn13="9780000000000",
        libby_title_id="12345",
        libby_share_url="https://manual.example.test/title/12345",
        format="ebook",
        status="completed",
        rating=4.5,
        notes="Keep this manual note.",
        completed_on=date(2026, 1, 1),
        manual_progress_percent=100,
        cover_url="https://manual.example.test/cover.jpg",
        cover_color="#ffffff",
        title_source="manual",
        author_source="manual",
        metadata_source="manual",
    )
    db.add(book)
    db.flush()
    db.add(
        ReadingEvent(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source="manual",
            event_type="manually_corrected",
            event_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
            progress_percent=100,
            raw_data={"changed_fields": {"status": {"from": "started", "to": "completed"}}},
        )
    )
    db.commit()
    db.refresh(book)
    return book


def libby_item():
    return parse_libby_export(
        {
            "version": 1,
            "timeline": [
                {
                    "cover": {
                        "url": "https://libby.example.test/cover.jpg",
                        "color": "#123456",
                        "format": "audiobook",
                    },
                    "title": {
                        "text": "Libby Title",
                        "url": "https://share.libbyapp.com/title/12345",
                        "titleId": "12345",
                    },
                    "author": "Libby Author",
                    "publisher": "Libby Publisher",
                    "isbn": "9781234567890",
                    "timestamp": 1767903363000,
                    "activity": "Borrowed",
                    "details": " 21 days ",
                    "library": {"key": "examplelibrary"},
                }
            ],
        }
    ).timeline[0]


def test_manual_book_edits_and_correction_events_survive_libby_reimports() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_manual_book_with_correction_event(db)
        item = libby_item()

        first_summary = process_libby_timeline_items(db, user_id=DEFAULT_LOCAL_USER_ID, items=[item])
        second_summary = process_libby_timeline_items(db, user_id=DEFAULT_LOCAL_USER_ID, items=[item])
        db.commit()

        book = db.query(Book).one()
        events = db.query(ReadingEvent).order_by(ReadingEvent.source, ReadingEvent.event_type).all()

    assert first_summary.books_created == 0
    assert first_summary.books_updated == 0
    assert first_summary.events_created == 1
    assert second_summary.books_created == 0
    assert second_summary.books_updated == 0
    assert second_summary.events_skipped == 1
    assert book.title == "Manual Title"
    assert book.primary_author_name == "Manual Author"
    assert book.publisher == "Manual Publisher"
    assert book.isbn13 == "9780000000000"
    assert book.libby_share_url == "https://manual.example.test/title/12345"
    assert book.format == "ebook"
    assert book.status == "completed"
    assert book.rating == 4.5
    assert book.notes == "Keep this manual note."
    assert book.completed_on == date(2026, 1, 1)
    assert book.manual_progress_percent == 100
    assert book.cover_url == "https://manual.example.test/cover.jpg"
    assert book.cover_color == "#ffffff"
    assert book.title_source == "manual"
    assert book.author_source == "manual"
    assert book.metadata_source == "manual"
    assert [(event.source, event.event_type) for event in events] == [
        ("libby", "borrowed"),
        ("manual", "manually_corrected"),
    ]
    manual_event = next(event for event in events if event.source == "manual")
    assert manual_event.raw_data == {"changed_fields": {"status": {"from": "started", "to": "completed"}}}
