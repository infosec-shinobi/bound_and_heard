from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, ScrapeJob, ScrapeJobItem, ScrapeSnapshot, User
from app.scrapers.libby_progress import parse_libby_progress
from app.services.scrape_snapshots import preserve_scrape_snapshot, snapshot_checksum


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_user_and_book(db: Session) -> Book:
    db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title="Scrapable Book",
        primary_author_name="Author",
        format="ebook",
        status="borrowed",
        metadata_source="libby",
        libby_title_id="libby-123",
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def test_scrape_job_stores_source_status_summary_and_timestamps() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user_and_book(db)
        job = ScrapeJob(
            user_id=DEFAULT_LOCAL_USER_ID,
            source="libby",
            status="queued",
            summary={"queued": 1, "skipped": 0},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

    assert job.source == "libby"
    assert job.status == "queued"
    assert job.summary == {"queued": 1, "skipped": 0}
    assert job.created_at is not None
    assert job.updated_at is not None


def test_scrape_job_item_tracks_book_queue_status_attempts_and_borrow_markers() -> None:
    session_factory = make_session_factory()
    latest_borrowed_at = datetime(2026, 6, 20, tzinfo=timezone.utc)
    last_scraped_borrowed_at = datetime(2026, 6, 1, tzinfo=timezone.utc)

    with session_factory() as db:
        book = add_user_and_book(db)
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="running")
        db.add(job)
        db.flush()
        item = ScrapeJobItem(
            job_id=job.id,
            book_id=book.id,
            status="queued",
            attempts=1,
            latest_borrowed_at=latest_borrowed_at,
            last_scraped_borrowed_at=last_scraped_borrowed_at,
            error_code="selector_missing",
            error_message="Progress selector was not found.",
        )
        db.add(item)
        db.commit()
        db.refresh(job)
        db.refresh(book)
        items = list(job.items)
        scrape_items = list(book.scrape_items)

    assert len(items) == 1
    assert items[0].status == "queued"
    assert items[0].attempts == 1
    assert items[0].latest_borrowed_at == latest_borrowed_at
    assert items[0].last_scraped_borrowed_at == last_scraped_borrowed_at
    assert items[0].error_code == "selector_missing"
    assert items[0].error_message == "Progress selector was not found."
    assert len(scrape_items) == 1
    assert scrape_items[0].id == items[0].id


def test_scrape_snapshot_stores_raw_snapshot_reference_and_parsed_progress() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        book = add_user_and_book(db)
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="running")
        db.add(job)
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book.id, status="succeeded")
        db.add(item)
        db.flush()
        snapshot = ScrapeSnapshot(
            item_id=item.id,
            snapshot_type="html",
            file_path="data/scrapes/libby/job-1/book-1.html",
            checksum="abc123",
            content_type="text/html",
            progress_percent=42.5,
            raw_data={"progress_text": "42%"},
        )
        db.add(snapshot)
        db.commit()
        db.refresh(item)
        snapshots = list(item.snapshots)

    assert len(snapshots) == 1
    assert snapshots[0].snapshot_type == "html"
    assert snapshots[0].file_path == "data/scrapes/libby/job-1/book-1.html"
    assert snapshots[0].checksum == "abc123"
    assert snapshots[0].content_type == "text/html"
    assert snapshots[0].progress_percent == 42.5
    assert snapshots[0].raw_data == {"progress_text": "42%"}


def test_preserve_scrape_snapshot_writes_file_and_creates_snapshot_record(tmp_path) -> None:
    session_factory = make_session_factory()
    content = "<html><body>Progress 42%</body></html>"

    with session_factory() as db:
        book = add_user_and_book(db)
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="running")
        db.add(job)
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book.id, status="failed")
        db.add(item)
        db.flush()

        preserved = preserve_scrape_snapshot(
            db,
            item=item,
            base_dir=tmp_path.as_posix(),
            snapshot_type="html",
            content=content,
            content_type="text/html",
            raw_data={"selector": "progress"},
            parsed_progress=parse_libby_progress(content, content_type="text/html"),
        )
        db.commit()
        db.refresh(item)
        snapshots = list(item.snapshots)

    assert preserved.content == content.encode("utf-8")
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.snapshot_type == "html"
    assert snapshot.content_type == "text/html"
    assert snapshot.checksum == snapshot_checksum(content.encode("utf-8"))
    assert snapshot.progress_percent == 42
    assert snapshot.raw_data["selector"] == "progress"
    assert snapshot.raw_data["parsed_progress"]["source"] == "scraped"
    assert snapshot.raw_data["parsed_progress"]["progress_percent"] == 42
    snapshot_path = tmp_path / "libby" / f"job-{job.id}" / f"item-{item.id}"
    assert snapshot.file_path.startswith(snapshot_path.as_posix())
    assert snapshot.file_path.endswith(".html")
    assert snapshot_path.exists()
