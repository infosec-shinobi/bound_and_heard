from collections.abc import Generator
from datetime import datetime, timezone
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Book, ReadingEvent, ScrapeJob, User
from app.services.libby_browser_worker import DESKTOP_CHROME_USER_AGENT


def make_scraping_client(admin_password: str | None = "secret") -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with TestingSessionLocal() as db:
        db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
        db.commit()

    app = create_app(
        Settings(
            admin_password=admin_password,
            session_secret="test-session-secret",
            database_url="sqlite:///:memory:",
            libby_browser_profile_dir="data/browser/test-libby-profile",
        )
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal


def add_libby_book(
    session_factory: sessionmaker[Session],
    *,
    title: str,
    metadata_source: str | None = "libby",
    libby_title_id: str | None = "title-1",
    libby_share_url: str | None = None,
    review_status: str | None = None,
    archived: bool = False,
    add_borrow: bool = True,
) -> int:
    with session_factory() as db:
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title=title,
            primary_author_name="Test Author",
            format="ebook",
            status="borrowed",
            metadata_source=metadata_source,
            libby_title_id=libby_title_id,
            libby_share_url=libby_share_url,
            review_status=review_status,
            archived_at=datetime.now(timezone.utc) if archived else None,
        )
        db.add(book)
        db.flush()
        if add_borrow:
            db.add(
                ReadingEvent(
                    user_id=DEFAULT_LOCAL_USER_ID,
                    book_id=book.id,
                    source="libby",
                    event_type="borrowed",
                    event_date=datetime(2026, 6, 20, tzinfo=timezone.utc),
                )
            )
        db.commit()
        return book.id


def test_libby_session_page_requires_admin_login() -> None:
    client, _ = make_scraping_client()

    response = client.get("/scraping/libby/session")

    assert response.status_code == 403


def test_libby_session_page_shows_manual_login_instructions_after_admin_login() -> None:
    client, _ = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/scraping/libby/session")

    assert response.status_code == 200
    assert "Libby Browser Session" in response.text
    assert "data/browser/test-libby-profile" in response.text
    assert "Credentials are not stored in the app database" in response.text
    assert "Open Libby Browser" in response.text


def test_libby_session_nav_link_is_present() -> None:
    client, _ = make_scraping_client(admin_password=None)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/scraping/libby/session"' in response.text


def test_libby_scrape_job_nav_link_is_present() -> None:
    client, _ = make_scraping_client(admin_password=None)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/scraping/libby/jobs/new"' in response.text


def test_open_libby_session_requires_admin_login() -> None:
    client, _ = make_scraping_client()

    response = client.post("/scraping/libby/session/open", follow_redirects=False)

    assert response.status_code == 403


def test_open_libby_session_uses_configured_profile_and_redirects(monkeypatch) -> None:
    client, _ = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    launched_commands: list[list[str]] = []

    def fake_popen(command: list[str], stdout: object, stderr: object) -> object:
        launched_commands.append(command)
        return object()

    monkeypatch.setattr("app.services.libby_browser.subprocess.Popen", fake_popen)

    response = client.post("/scraping/libby/session/open", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/scraping/libby/session?launched=true"
    assert launched_commands == [
        [
            sys.executable,
            "-m",
            "app.services.libby_browser_worker",
            "data/browser/test-libby-profile",
        ]
    ]


def test_open_libby_session_shows_launch_error(monkeypatch) -> None:
    client, _ = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})

    def fake_popen(command: list[str], stdout: object, stderr: object) -> object:
        raise OSError("Browser profile is locked.")

    monkeypatch.setattr("app.services.libby_browser.subprocess.Popen", fake_popen)

    response = client.post("/scraping/libby/session/open")

    assert response.status_code == 200
    assert "Browser profile is locked." in response.text


def test_libby_browser_worker_uses_desktop_chrome_user_agent() -> None:
    assert "Windows NT 10.0" in DESKTOP_CHROME_USER_AGENT
    assert "Chrome/" in DESKTOP_CHROME_USER_AGENT
    assert "Safari/537.36" in DESKTOP_CHROME_USER_AGENT


def test_new_libby_scrape_job_page_requires_admin_login() -> None:
    client, _ = make_scraping_client()

    response = client.get("/scraping/libby/jobs/new")

    assert response.status_code == 403


def test_new_libby_scrape_job_page_previews_candidate_counts() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    add_libby_book(session_factory, title="Queued Book", libby_title_id="queued-title")
    add_libby_book(session_factory, title="Archived Book", libby_title_id="archived-title", archived=True)
    add_libby_book(session_factory, title="Ignored Book", libby_title_id="ignored-title", review_status="ignored")
    add_libby_book(session_factory, title="No Context Book", libby_title_id=None)
    add_libby_book(session_factory, title="No Borrow Book", libby_title_id="no-borrow-title", add_borrow=False)
    add_libby_book(session_factory, title="Manual Book", metadata_source="manual", libby_title_id="manual-title")

    response = client.get("/scraping/libby/jobs/new")

    assert response.status_code == 200
    assert "New Libby Progress Scrape Job" in response.text
    assert "Queued Book" in response.text
    assert "Archived" in response.text
    assert "Marked ignored" in response.text
    assert "Missing Libby title ID or share URL" in response.text
    assert "Missing Libby borrow event" in response.text
    assert "Manual Book" not in response.text


def test_create_libby_scrape_job_requires_admin_login() -> None:
    client, _ = make_scraping_client()

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 403


def test_create_libby_scrape_job_persists_pending_job_summary() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    queued_book_id = add_libby_book(session_factory, title="Queued Book", libby_title_id="queued-title")
    add_libby_book(session_factory, title="Archived Book", libby_title_id="archived-title", archived=True)
    add_libby_book(session_factory, title="No Context Book", libby_title_id=None)

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/scraping/libby/jobs/new?created_job_id=")
    with session_factory() as db:
        job = db.query(ScrapeJob).one()
        assert job.source == "libby"
        assert job.status == "pending"
        assert job.summary == {
            "queued_count": 1,
            "skipped_count": 1,
            "ineligible_count": 1,
            "queued_book_ids": [queued_book_id],
            "note": "Per-book scrape items are created when queue processing is implemented.",
        }


def test_create_libby_scrape_job_with_no_eligible_books_redirects_without_job() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    add_libby_book(session_factory, title="No Context Book", libby_title_id=None)

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/scraping/libby/jobs/new"
    with session_factory() as db:
        assert db.query(ScrapeJob).count() == 0
