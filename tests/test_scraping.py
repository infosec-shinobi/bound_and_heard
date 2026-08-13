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
from app.models import Book, BookProgress, ReadingEvent, ScrapeJob, ScrapeJobItem, User
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
    last_scraped_borrowed_at: datetime | None = None,
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
        if last_scraped_borrowed_at is not None:
            db.add(
                BookProgress(
                    user_id=DEFAULT_LOCAL_USER_ID,
                    book_id=book.id,
                    source="libby",
                    last_scraped_borrowed_at=last_scraped_borrowed_at,
                )
            )
        db.commit()
        return book.id


def add_scrape_job(
    session_factory: sessionmaker[Session],
    *,
    status: str = "pending",
    with_items: bool = False,
) -> int:
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status=status)
        db.add(job)
        if with_items:
            db.flush()
            book = Book(
                user_id=DEFAULT_LOCAL_USER_ID,
                title="Cancelable Book",
                primary_author_name="Test Author",
                format="ebook",
                status="borrowed",
                metadata_source="libby",
                libby_title_id="cancelable-title",
            )
            db.add(book)
            db.flush()
            db.add(ScrapeJobItem(job_id=job.id, book_id=book.id, status="queued"))
        db.commit()
        return job.id


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
    assert 'name="book_ids"' in response.text
    assert 'data-select-book-ids="all"' in response.text
    assert 'data-select-book-ids="none"' in response.text


def test_new_libby_scrape_job_page_skips_unchanged_books() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    add_libby_book(
        session_factory,
        title="Already Scraped Book",
        libby_title_id="already-scraped-title",
        last_scraped_borrowed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )

    response = client.get("/scraping/libby/jobs/new")

    assert response.status_code == 200
    assert "Already Scraped Book" in response.text
    assert "Latest borrow already scraped" in response.text
    assert "No queued books." in response.text


def test_new_libby_scrape_job_page_force_rescrape_bypasses_unchanged_skip() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    add_libby_book(
        session_factory,
        title="Already Scraped Book",
        libby_title_id="already-scraped-title",
        last_scraped_borrowed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )

    response = client.get("/scraping/libby/jobs/new?force=true")

    assert response.status_code == 200
    assert "Already Scraped Book" in response.text
    assert "Latest borrow already scraped" not in response.text
    assert 'name="force" value="true"' in response.text


def test_create_libby_scrape_job_requires_admin_login() -> None:
    client, _ = make_scraping_client()

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 403


def test_create_libby_scrape_job_persists_pending_job_and_items() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    last_scraped_borrowed_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    queued_book_id = add_libby_book(
        session_factory,
        title="Queued Book",
        libby_title_id="queued-title",
        last_scraped_borrowed_at=last_scraped_borrowed_at,
    )
    add_libby_book(session_factory, title="Archived Book", libby_title_id="archived-title", archived=True)
    add_libby_book(session_factory, title="No Context Book", libby_title_id=None)

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/scraping/libby/jobs/")
    with session_factory() as db:
        job = db.query(ScrapeJob).one()
        assert job.source == "libby"
        assert job.status == "pending"
        assert job.summary == {
            "queued_count": 1,
            "skipped_count": 1,
            "ineligible_count": 1,
            "queued_book_ids": [queued_book_id],
            "process_mode": "one_item_at_a_time",
            "force": False,
            "selected_book_ids": [],
        }
        item = db.query(ScrapeJobItem).one()
        assert item.job_id == job.id
        assert item.book_id == queued_book_id
        assert item.status == "queued"
        assert item.attempts == 0
        assert item.latest_borrowed_at == datetime(2026, 6, 20)
        assert item.last_scraped_borrowed_at == last_scraped_borrowed_at.replace(tzinfo=None)


def test_create_libby_scrape_job_with_no_eligible_books_redirects_without_job() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    add_libby_book(session_factory, title="No Context Book", libby_title_id=None)

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/scraping/libby/jobs/new"
    with session_factory() as db:
        assert db.query(ScrapeJob).count() == 0


def test_create_libby_scrape_job_skips_unchanged_books() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    add_libby_book(
        session_factory,
        title="Already Scraped Book",
        libby_title_id="already-scraped-title",
        last_scraped_borrowed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/scraping/libby/jobs/new"
    with session_factory() as db:
        assert db.query(ScrapeJob).count() == 0
        assert db.query(ScrapeJobItem).count() == 0


def test_create_libby_scrape_job_force_rescrape_queues_unchanged_books() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    queued_book_id = add_libby_book(
        session_factory,
        title="Already Scraped Book",
        libby_title_id="already-scraped-title",
        last_scraped_borrowed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
    )

    response = client.post("/scraping/libby/jobs", data={"force": "true"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/scraping/libby/jobs/")
    with session_factory() as db:
        job = db.query(ScrapeJob).one()
        item = db.query(ScrapeJobItem).one()
        assert job.summary["force"] is True
        assert job.summary["queued_book_ids"] == [queued_book_id]
        assert item.book_id == queued_book_id


def test_create_libby_scrape_job_with_selected_books_only_queues_selected_books() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    selected_book_id = add_libby_book(session_factory, title="Selected Book", libby_title_id="selected-title")
    unselected_book_id = add_libby_book(session_factory, title="Unselected Book", libby_title_id="unselected-title")

    response = client.post(
        "/scraping/libby/jobs",
        data={"book_ids": str(selected_book_id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        job = db.query(ScrapeJob).one()
        items = db.query(ScrapeJobItem).all()
        assert job.summary["queued_count"] == 1
        assert job.summary["skipped_count"] == 1
        assert job.summary["queued_book_ids"] == [selected_book_id]
        assert job.summary["selected_book_ids"] == [selected_book_id]
        assert [item.book_id for item in items] == [selected_book_id]
        assert unselected_book_id not in job.summary["queued_book_ids"]


def test_create_libby_scrape_job_without_selected_books_queues_all_eligible_books() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    first_book_id = add_libby_book(session_factory, title="First Book", libby_title_id="first-title")
    second_book_id = add_libby_book(session_factory, title="Second Book", libby_title_id="second-title")

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        job = db.query(ScrapeJob).one()
        item_book_ids = [item.book_id for item in db.query(ScrapeJobItem).order_by(ScrapeJobItem.book_id).all()]
        assert job.summary["queued_count"] == 2
        assert job.summary["selected_book_ids"] == []
        assert sorted(job.summary["queued_book_ids"]) == sorted([first_book_id, second_book_id])
        assert item_book_ids == sorted([first_book_id, second_book_id])


def test_create_libby_scrape_job_redirects_to_existing_active_job() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    add_libby_book(session_factory, title="Queued Book", libby_title_id="queued-title")
    existing_job_id = add_scrape_job(session_factory, status="running")

    response = client.post("/scraping/libby/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/scraping/libby/jobs/{existing_job_id}?")
    with session_factory() as db:
        assert db.query(ScrapeJob).count() == 1
        assert db.query(ScrapeJobItem).count() == 0


def test_new_libby_scrape_job_page_shows_active_job_protection() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    existing_job_id = add_scrape_job(session_factory, status="pending")

    response = client.get("/scraping/libby/jobs/new")

    assert response.status_code == 200
    assert f"Active Libby scrape job #{existing_job_id}" in response.text
    assert f'href="/scraping/libby/jobs/{existing_job_id}"' in response.text


def test_libby_scrape_job_detail_shows_item_statuses_and_errors() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    queued_book_id = add_libby_book(session_factory, title="Queued Book", libby_title_id="queued-title")
    failed_book_id = add_libby_book(session_factory, title="Failed Book", libby_title_id="failed-title")
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="running")
        db.add(job)
        db.flush()
        db.add(
            ScrapeJobItem(
                job_id=job.id,
                book_id=queued_book_id,
                status="queued",
                latest_borrowed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
            )
        )
        db.add(
            ScrapeJobItem(
                job_id=job.id,
                book_id=failed_book_id,
                status="failed",
                attempts=1,
                latest_borrowed_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
                error_code="selector_missing",
                error_message="Progress selector was not found.",
            )
        )
        db.commit()
        job_id = job.id

    response = client.get(f"/scraping/libby/jobs/{job_id}")

    assert response.status_code == 200
    assert f"Scrape Job #{job_id}" in response.text
    assert "Queued Book" in response.text
    assert "Failed Book" in response.text
    assert "Progress selector was not found." in response.text
    assert "Each book has an independent item" in response.text


def test_libby_scrape_job_detail_shows_summary_and_cancel_action_for_active_job() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    with session_factory() as db:
        job = ScrapeJob(
            user_id=DEFAULT_LOCAL_USER_ID,
            source="libby",
            status="pending",
            summary={"queued_count": 1, "skipped_count": 2, "ineligible_count": 3, "force": True},
        )
        db.add(job)
        db.commit()
        job_id = job.id

    response = client.get(f"/scraping/libby/jobs/{job_id}")

    assert response.status_code == 200
    assert "Skipped at creation" in response.text
    assert "Force re-scrape" in response.text
    assert f'action="/scraping/libby/jobs/{job_id}/cancel"' in response.text


def test_cancel_libby_scrape_job_marks_active_job_cancelled_and_open_items_skipped() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    job_id = add_scrape_job(session_factory, status="running", with_items=True)

    response = client.post(f"/scraping/libby/jobs/{job_id}/cancel", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/scraping/libby/jobs/{job_id}?")
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "cancelled"
        assert job.finished_at is not None
        assert "cancelled_at" in job.summary
        item = db.query(ScrapeJobItem).one()
        assert item.status == "skipped"
        assert item.error_code == "job_cancelled"


def test_cancel_libby_scrape_job_requires_admin_login() -> None:
    client, session_factory = make_scraping_client()
    job_id = add_scrape_job(session_factory, status="pending")

    response = client.post(f"/scraping/libby/jobs/{job_id}/cancel", follow_redirects=False)

    assert response.status_code == 403


def test_cancel_libby_scrape_job_does_not_cancel_completed_job() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    job_id = add_scrape_job(session_factory, status="completed")

    response = client.post(f"/scraping/libby/jobs/{job_id}/cancel", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "completed"


def test_libby_scrape_job_detail_requires_admin_login() -> None:
    client, session_factory = make_scraping_client()
    job_id = add_scrape_job(session_factory)

    response = client.get(f"/scraping/libby/jobs/{job_id}")

    assert response.status_code == 403


def test_libby_scrape_job_detail_returns_not_found_for_missing_job() -> None:
    client, _ = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/scraping/libby/jobs/999")

    assert response.status_code == 404
    assert "Scrape job not found" in response.text
