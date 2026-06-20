from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.importers.libby_json import build_libby_source_event_id, parse_libby_export
from app.models import Book, ReadingEvent, User
from app.services.import_service import create_libby_reading_event


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_book(db: Session) -> Book:
    db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title="A Sample Book",
        primary_author_name="Example Author",
        format="audiobook",
        status="borrowed",
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def libby_export(*, title_id: str = "12345", activity: str = "Borrowed") -> dict[str, object]:
    return {
        "version": 1,
        "timeline": [
            {
                "cover": {"format": "audiobook"},
                "title": {
                    "text": "A Sample Book",
                    "url": "https://share.libbyapp.com/title/12345",
                    "titleId": title_id,
                },
                "author": "Example Author",
                "publisher": "Example Publisher",
                "isbn": "9781234567890",
                "timestamp": 1767903363000,
                "activity": activity,
                "details": " 21 days ",
                "library": {"text": "Example Library", "key": "examplelibrary"},
            }
        ],
    }


def test_create_libby_reading_event_stores_libby_source_and_source_event_id() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        book = add_book(db)
        item = parse_libby_export(libby_export()).timeline[0]

        result = create_libby_reading_event(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            item=item,
            event_type="borrowed",
        )
        db.commit()

        event = db.query(ReadingEvent).one()

    assert result.created is True
    assert event.source == "libby"
    assert event.source_event_id == build_libby_source_event_id(item)
    assert event.event_type == "borrowed"
    assert event.raw_data == {"libby": item.raw_item}


def test_overlapping_libby_exports_do_not_create_duplicate_reading_events() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        book = add_book(db)
        first_item = parse_libby_export(libby_export()).timeline[0]
        overlapping_item = parse_libby_export(libby_export()).timeline[0]

        first_result = create_libby_reading_event(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            item=first_item,
            event_type="borrowed",
        )
        second_result = create_libby_reading_event(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            item=overlapping_item,
            event_type="borrowed",
        )
        db.commit()

        events = db.query(ReadingEvent).all()

    assert first_result.created is True
    assert second_result.created is False
    assert first_result.event.id == second_result.event.id
    assert len(events) == 1


def test_different_libby_source_event_key_creates_distinct_event() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        book = add_book(db)
        first_item = parse_libby_export(libby_export(title_id="12345")).timeline[0]
        second_item = parse_libby_export(libby_export(title_id="67890")).timeline[0]

        create_libby_reading_event(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            item=first_item,
            event_type="borrowed",
        )
        create_libby_reading_event(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            item=second_item,
            event_type="borrowed",
        )
        db.commit()

        events = db.query(ReadingEvent).order_by(ReadingEvent.source_event_id).all()

    assert len(events) == 2
    assert events[0].source_event_id != events[1].source_event_id


def test_libby_event_creation_requires_timestamp() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        book = add_book(db)
        item = parse_libby_export({"version": 1, "timeline": [{"title": {"titleId": "12345"}}]}).timeline[0]

        try:
            create_libby_reading_event(
                db,
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                item=item,
                event_type="borrowed",
            )
        except ValueError as exc:
            assert "timestamp" in str(exc)
        else:
            raise AssertionError("Expected missing timestamp to fail.")
