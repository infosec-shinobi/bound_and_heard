from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, BookProgress, ReadingEvent, ScrapeJob, ScrapeJobItem, User
from app.scrapers.libby_progress import parse_libby_progress
from app.services.scrape_progress import apply_scraped_progress


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_scrape_item(db: Session, *, book: Book) -> ScrapeJobItem:
    job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="running")
    db.add(job)
    db.flush()
    item = ScrapeJobItem(
        job_id=job.id,
        book_id=book.id,
        status="running",
        latest_borrowed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )
    db.add(item)
    db.flush()
    return item


def add_book(db: Session, **values: object) -> Book:
    db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title="Scraped Book",
        primary_author_name="Author",
        format="ebook",
        status="borrowed",
        metadata_source="libby",
        libby_title_id="libby-1",
        **values,
    )
    db.add(book)
    db.flush()
    return book


def test_apply_scraped_progress_creates_book_progress_and_scraped_event() -> None:
    session_factory = make_session_factory()
    observed_at = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)
    with session_factory() as db:
        book = add_book(db)
        item = add_scrape_item(db, book=book)

        progress = apply_scraped_progress(
            db,
            item=item,
            parsed=parse_libby_progress("42% Page 126 of 300"),
            observed_at=observed_at,
        )
        db.commit()

        assert progress.source == "scraped"
        assert progress.progress_percent == 42
        assert progress.position_pages == 126
        assert progress.total_pages == 300
        assert progress.enjoyed_seconds is None
        assert progress.last_borrowed_at == item.latest_borrowed_at
        assert progress.last_scraped_borrowed_at == item.latest_borrowed_at
        event = db.query(ReadingEvent).filter_by(book_id=book.id, source="scraped").one()
        assert event.event_type == "progress_seen"
        assert event.progress_percent == 42


def test_apply_scraped_completed_progress_sets_safe_completion_fields() -> None:
    session_factory = make_session_factory()
    observed_at = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)
    with session_factory() as db:
        book = add_book(db)
        item = add_scrape_item(db, book=book)

        apply_scraped_progress(db, item=item, parsed=parse_libby_progress("Completed"), observed_at=observed_at)
        db.commit()

        assert book.status == "completed"
        assert book.completed_on == observed_at.date()
        event = db.query(ReadingEvent).filter_by(book_id=book.id, source="scraped").one()
        assert event.event_type == "completed"


def test_apply_scraped_progress_does_not_overwrite_manual_progress() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db, manual_progress_percent=10)
        item = add_scrape_item(db, book=book)

        progress = apply_scraped_progress(db, item=item, parsed=parse_libby_progress("42%"))
        db.commit()

        assert book.manual_progress_percent == 10
        assert progress.progress_percent is None


def test_apply_scraped_completed_progress_does_not_overwrite_manual_completion_date() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db)
        item = add_scrape_item(db, book=book)
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                event_type="manually_corrected",
                event_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                raw_data={"changed_fields": {"completed_on": {"from": None, "to": "2026-06-01"}}},
            )
        )
        db.flush()

        apply_scraped_progress(db, item=item, parsed=parse_libby_progress("Completed"))
        db.commit()

        assert book.completed_on is None
        assert book.status == "completed"


def test_apply_scraped_progress_preserves_existing_libby_and_manual_events() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db)
        item = add_scrape_item(db, book=book)
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="libby",
                event_type="borrowed",
                event_date=datetime(2026, 6, 20, tzinfo=timezone.utc),
            )
        )
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                event_type="manually_corrected",
                event_date=datetime(2026, 6, 21, tzinfo=timezone.utc),
                raw_data={"changed_fields": {"status": {"from": "borrowed", "to": "started"}}},
            )
        )

        apply_scraped_progress(db, item=item, parsed=parse_libby_progress("42%"))
        db.commit()

        event_sources = [event.source for event in db.query(ReadingEvent).order_by(ReadingEvent.id).all()]
        assert event_sources == ["libby", "manual", "scraped"]


def test_apply_scraped_progress_updates_existing_scraped_event_for_same_item() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db)
        item = add_scrape_item(db, book=book)
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="scraped",
                source_event_id=f"scrape_item:{item.id}:progress_seen",
                event_type="progress_seen",
                event_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                progress_percent=None,
            )
        )
        db.commit()

        apply_scraped_progress(db, item=item, parsed=parse_libby_progress("42%"))
        db.commit()

        events = db.query(ReadingEvent).filter_by(book_id=book.id, source="scraped").all()
        assert len(events) == 1
        assert events[0].progress_percent == 42


def test_apply_scraped_progress_sets_enjoyed_seconds_from_libby_duration() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db)
        book.format = "audiobook"
        item = add_scrape_item(db, book=book)

        progress = apply_scraped_progress(
            db,
            item=item,
            parsed=parse_libby_progress("Starting on 28 Mar, reading for 5 hours, 42 minutes."),
        )
        db.commit()

        assert progress.enjoyed_seconds == 20520
        assert progress.read_count is None
