from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, ScrapeJob, ScrapeJobItem, User
from app.scrapers.libby_progress import parse_libby_progress
from app.services.libby_scrape_runner import JOURNEY_READY_SCRIPT, has_parseable_progress, scrape_url_for_item


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_scrape_url_for_item_uses_authenticated_journey_url_not_public_share_url() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Book",
            format="ebook",
            status="borrowed",
            metadata_source="libby",
            libby_title_id="12345",
            libby_share_url="https://share.libbyapp.com/title/12345",
        )
        db.add(book)
        db.flush()
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="running")
        db.add(job)
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book.id, status="queued")
        db.add(item)
        db.commit()
        db.refresh(item)

        assert scrape_url_for_item(item) == "https://libbyapp.com/shelf/journey/12345"


def test_journey_ready_script_waits_for_progress_signals_not_loading_shell() -> None:
    assert "No progress yet" in JOURNEY_READY_SCRIPT
    assert "Updating" in JOURNEY_READY_SCRIPT
    assert "listened" in JOURNEY_READY_SCRIPT
    assert "\\b(?:left|remaining|listened|read|completed|finished)\\b" in JOURNEY_READY_SCRIPT


def test_has_parseable_progress_rejects_loading_shell_text() -> None:
    parsed = parse_libby_progress("Updating LOADING Shelf Reading Journey", content_type="text/plain")

    assert has_parseable_progress(parsed) is False
