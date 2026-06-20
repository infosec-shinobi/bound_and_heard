from datetime import timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.importers.libby_json import parse_libby_export
from app.models import Book, ReadingEvent, User
from app.services.import_service import libby_activity_to_event_type, process_libby_timeline_items


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


def timeline_item(
    *,
    activity: str = "Borrowed",
    timestamp: int | None = 1767903363000,
    title_id: str = "12345",
):
    item: dict[str, object] = {
        "cover": {"format": "audiobook"},
        "title": {
            "text": "A Sample Book",
            "url": f"https://share.libbyapp.com/title/{title_id}",
            "titleId": title_id,
        },
        "author": "Example Author",
        "publisher": "Example Publisher",
        "isbn": "9781234567890",
        "activity": activity,
        "details": " 21 days ",
        "library": {"text": "Example Library", "key": "examplelibrary"},
    }
    if timestamp is not None:
        item["timestamp"] = timestamp
    return parse_libby_export({"version": 1, "timeline": [item]}).timeline[0]


def test_libby_activity_to_event_type_maps_known_activities() -> None:
    assert libby_activity_to_event_type("Borrowed") == "borrowed"
    assert libby_activity_to_event_type("Returned") == "returned"
    assert libby_activity_to_event_type("Started") == "started"
    assert libby_activity_to_event_type("Progress Seen") == "progress_seen"
    assert libby_activity_to_event_type("Completed") == "completed"
    assert libby_activity_to_event_type("Something Else") is None


def test_process_libby_timeline_items_creates_borrowed_event_with_timezone_and_raw_data() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        item = timeline_item(activity="Borrowed")

        summary = process_libby_timeline_items(db, user_id=DEFAULT_LOCAL_USER_ID, items=[item])
        db.commit()
        event = db.query(ReadingEvent).one()

    assert item.timestamp is not None
    assert item.timestamp.tzinfo == timezone.utc
    assert summary.books_created == 1
    assert summary.events_created == 1
    assert summary.events_skipped == 0
    assert event.event_type == "borrowed"
    assert event.raw_data == {"libby": item.raw_item}


def test_process_libby_timeline_items_creates_returned_started_progress_and_completed_events() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        items = [
            timeline_item(activity="Returned", timestamp=1767903363000, title_id="returned"),
            timeline_item(activity="Started", timestamp=1767903364000, title_id="started"),
            timeline_item(activity="Progress Seen", timestamp=1767903365000, title_id="progress"),
            timeline_item(activity="Completed", timestamp=1767903366000, title_id="completed"),
        ]

        summary = process_libby_timeline_items(db, user_id=DEFAULT_LOCAL_USER_ID, items=items)
        db.commit()
        event_types = [event.event_type for event in db.query(ReadingEvent).order_by(ReadingEvent.event_date).all()]

    assert summary.books_created == 4
    assert summary.events_created == 4
    assert event_types == ["returned", "started", "progress_seen", "completed"]


def test_process_libby_timeline_items_skips_duplicate_events_and_counts_summary() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        item = timeline_item(activity="Borrowed")

        first_summary = process_libby_timeline_items(db, user_id=DEFAULT_LOCAL_USER_ID, items=[item])
        second_summary = process_libby_timeline_items(db, user_id=DEFAULT_LOCAL_USER_ID, items=[item])
        db.commit()

        assert db.query(Book).count() == 1
        assert db.query(ReadingEvent).count() == 1

    assert first_summary.events_created == 1
    assert first_summary.events_skipped == 0
    assert second_summary.books_created == 0
    assert second_summary.events_created == 0
    assert second_summary.events_skipped == 1


def test_process_libby_timeline_items_counts_unsupported_or_timestampless_items() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        items = [
            timeline_item(activity="Tagged", timestamp=1767903363000, title_id="tagged"),
            timeline_item(activity="Borrowed", timestamp=None, title_id="missing-timestamp"),
        ]

        summary = process_libby_timeline_items(db, user_id=DEFAULT_LOCAL_USER_ID, items=items)
        db.commit()

        assert db.query(Book).count() == 2
        assert db.query(ReadingEvent).count() == 0

    assert summary.books_created == 2
    assert summary.events_created == 0
    assert summary.events_skipped == 0
    assert summary.unsupported_events == 2
