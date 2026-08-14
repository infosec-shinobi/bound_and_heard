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
from app.models import Book, BookProgress, ReadingEvent, ScrapeJob, ScrapeJobItem, ScrapeSnapshot, User
from app.services.libby_browser_worker import DESKTOP_CHROME_USER_AGENT
from app.services.scrape_safety import polite_delay_seconds, should_attempt_item, wait_polite_delay


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
            scraped_dir="data/scraped/test",
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
    assert 'href="/scraping/libby/jobs"' in response.text


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


def test_polite_delay_seconds_is_between_five_and_fifteen_seconds() -> None:
    delays = [polite_delay_seconds() for _ in range(100)]

    assert all(5 <= delay <= 15 for delay in delays)
    assert len(set(delays)) > 1


def test_wait_polite_delay_is_testable_without_real_sleep() -> None:
    slept: list[float] = []

    delay = wait_polite_delay(sleeper=slept.append)

    assert slept == [delay]
    assert 5 <= delay <= 15


def test_should_attempt_item_avoids_tight_retry_loops() -> None:
    assert should_attempt_item(0) is True
    assert should_attempt_item(1) is False


def test_new_libby_scrape_job_page_requires_admin_login() -> None:
    client, _ = make_scraping_client()

    response = client.get("/scraping/libby/jobs/new")

    assert response.status_code == 403


def test_libby_scrape_jobs_index_requires_admin_login() -> None:
    client, _ = make_scraping_client()

    response = client.get("/scraping/libby/jobs")

    assert response.status_code == 403


def test_libby_scrape_jobs_index_lists_old_jobs_and_links_to_detail() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="History Book", libby_title_id="history-title")
    with session_factory() as db:
        completed_job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="completed", finished_at=datetime.now(timezone.utc))
        pending_job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="pending")
        db.add_all([completed_job, pending_job])
        db.flush()
        retryable_item = ScrapeJobItem(job_id=completed_job.id, book_id=book_id, status="succeeded")
        queued_item = ScrapeJobItem(job_id=pending_job.id, book_id=book_id, status="queued")
        db.add_all([retryable_item, queued_item])
        db.flush()
        db.add(
            ScrapeSnapshot(
                item_id=retryable_item.id,
                snapshot_type="text",
                file_path="data/scraped/test/libby/job-1/item-1/loading.txt",
                raw_data={"parsed_progress": {"progress_percent": None, "position_pages": None, "position_seconds": None}},
            )
        )
        db.commit()
        completed_job_id = completed_job.id
        pending_job_id = pending_job.id

    response = client.get("/scraping/libby/jobs")

    assert response.status_code == 200
    assert "Libby Scrape Jobs" in response.text
    assert f"Job #{completed_job_id}" in response.text
    assert f"/scraping/libby/jobs/{completed_job_id}" in response.text
    assert f"Job #{pending_job_id}" in response.text
    assert "1 item retryable" in response.text
    assert "Open active job" in response.text


def test_delete_libby_scrape_job_removes_items_and_snapshot_records() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="Delete Job Book", libby_title_id="delete-job-title")
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="completed", finished_at=datetime.now(timezone.utc))
        db.add(job)
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book_id, status="succeeded")
        db.add(item)
        db.flush()
        snapshot = ScrapeSnapshot(item_id=item.id, snapshot_type="text", file_path="data/scraped/test/file.txt")
        db.add(snapshot)
        db.commit()
        job_id = job.id
        item_id = item.id
        snapshot_id = snapshot.id

    response = client.post(f"/scraping/libby/jobs/{job_id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/scraping/libby/jobs?")
    with session_factory() as db:
        assert db.get(ScrapeJob, job_id) is None
        assert db.get(ScrapeJobItem, item_id) is None
        assert db.get(ScrapeSnapshot, snapshot_id) is None


def test_delete_libby_scrape_job_blocks_running_jobs() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    job_id = add_scrape_job(session_factory, status="running", with_items=False)

    response = client.post(f"/scraping/libby/jobs/{job_id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/scraping/libby/jobs/{job_id}?")
    with session_factory() as db:
        assert db.get(ScrapeJob, job_id) is not None


def test_recover_failed_libby_scrape_job_reopens_stuck_items() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="Recover Job Book", libby_title_id="recover-job-title")
    with session_factory() as db:
        job = ScrapeJob(
            user_id=DEFAULT_LOCAL_USER_ID,
            source="libby",
            status="failed",
            finished_at=datetime.now(timezone.utc),
            summary={"runner_error": "Connection closed"},
        )
        db.add(job)
        db.flush()
        db.add_all(
            [
                ScrapeJobItem(job_id=job.id, book_id=book_id, status="queued"),
                ScrapeJobItem(job_id=job.id, book_id=book_id, status="running", error_code="RuntimeError", error_message="Connection closed"),
                ScrapeJobItem(job_id=job.id, book_id=book_id, status="failed", error_code="ValueError", error_message="No progress"),
            ]
        )
        db.commit()
        job_id = job.id

    detail_response = client.get(f"/scraping/libby/jobs/{job_id}")

    assert detail_response.status_code == 200
    assert "Recover Job" in detail_response.text

    response = client.post(f"/scraping/libby/jobs/{job_id}/recover", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "pending"
        assert job.finished_at is None
        assert "runner_error" not in job.summary
        assert job.summary["recovered_item_count"] == 3
        assert {item.status for item in job.items} == {"queued"}
        assert all(item.error_code is None for item in job.items)


def test_recover_running_libby_scrape_job_is_blocked() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    job_id = add_scrape_job(session_factory, status="running", with_items=True)

    response = client.post(f"/scraping/libby/jobs/{job_id}/recover", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "running"


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
    assert "Missing Libby title ID" in response.text
    assert "Missing Libby borrow event" in response.text
    assert "Manual Book" not in response.text
    assert 'name="book_ids"' in response.text
    assert 'data-select-book-ids="all"' in response.text
    assert 'data-select-book-ids="none"' in response.text
    assert 'href="/scraping/libby/jobs"' in response.text


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
        db.flush()
        failed_item = db.query(ScrapeJobItem).filter_by(book_id=failed_book_id).one()
        db.add(
            ScrapeSnapshot(
                item_id=failed_item.id,
                snapshot_type="html",
                file_path="data/scraped/test/libby/job-1/item-2/failure.html",
                checksum="abc123def456",
                content_type="text/html",
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
    assert "data/scraped/test/libby/job-1/item-2/failure.html" in response.text
    assert "abc123def456" in response.text


def test_requeue_skipped_libby_scrape_item_clears_skipped_status() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="Skipped Book", libby_title_id="skipped-title")
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="pending")
        db.add(job)
        db.flush()
        item = ScrapeJobItem(
            job_id=job.id,
            book_id=book_id,
            status="skipped",
            error_code="job_cancelled",
            error_message="Skipped earlier.",
        )
        db.add(item)
        db.commit()
        job_id = job.id
        item_id = item.id

    response = client.post(f"/scraping/libby/jobs/{job_id}/items/{item_id}/requeue", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        item = db.get(ScrapeJobItem, item_id)
        assert item is not None
        assert item.status == "queued"
        assert item.error_code is None
        assert item.error_message is None


def test_requeue_skipped_item_from_completed_job_reopens_job() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="Skipped Book", libby_title_id="skipped-title")
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="completed", finished_at=datetime.now(timezone.utc))
        db.add(job)
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book_id, status="skipped")
        db.add(item)
        db.commit()
        job_id = job.id
        item_id = item.id

    response = client.post(f"/scraping/libby/jobs/{job_id}/items/{item_id}/requeue", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        item = db.get(ScrapeJobItem, item_id)
        assert job is not None
        assert item is not None
        assert job.status == "pending"
        assert job.finished_at is None
        assert item.status == "queued"


def test_skip_failed_libby_scrape_item_marks_item_skipped() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="Failed To Skip Book", libby_title_id="failed-skip-title")
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="completed", finished_at=datetime.now(timezone.utc))
        db.add(job)
        db.flush()
        item = ScrapeJobItem(
            job_id=job.id,
            book_id=book_id,
            status="failed",
            error_code="ValueError",
            error_message="No progress parsed.",
        )
        db.add(item)
        db.commit()
        job_id = job.id
        item_id = item.id

    detail_response = client.get(f"/scraping/libby/jobs/{job_id}")

    assert detail_response.status_code == 200
    assert "Retry" in detail_response.text
    assert "Skip" in detail_response.text

    response = client.post(f"/scraping/libby/jobs/{job_id}/items/{item_id}/skip", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        item = db.get(ScrapeJobItem, item_id)
        assert item is not None
        assert item.status == "skipped"
        assert item.error_code == "user_skipped"
        assert item.error_message == "Item was skipped by user after failure."
        assert item.finished_at is not None


def test_skip_libby_scrape_item_requires_failed_status() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="Queued Not Skipped Book", libby_title_id="queued-no-skip-title")
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="pending")
        db.add(job)
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book_id, status="queued")
        db.add(item)
        db.commit()
        job_id = job.id
        item_id = item.id

    response = client.post(f"/scraping/libby/jobs/{job_id}/items/{item_id}/skip", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        item = db.get(ScrapeJobItem, item_id)
        assert item is not None
        assert item.status == "queued"


def test_completed_empty_progress_item_can_be_retried_and_clears_scraped_borrow_gate() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    book_id = add_libby_book(session_factory, title="Empty Success Book", libby_title_id="empty-title")
    with session_factory() as db:
        book = db.get(Book, book_id)
        assert book is not None
        progress = BookProgress(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book_id,
            source="scraped",
            last_scraped_borrowed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="completed", finished_at=datetime.now(timezone.utc))
        db.add_all([progress, job])
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book_id, status="succeeded")
        db.add(item)
        db.flush()
        db.add(
            ScrapeSnapshot(
                item_id=item.id,
                snapshot_type="text",
                file_path="data/scraped/test/libby/job-1/item-1/loading.txt",
                checksum="f822fe5c8b62",
                content_type="text/plain",
                raw_data={"parsed_progress": {"progress_percent": None, "position_pages": None, "position_seconds": None}},
            )
        )
        db.commit()
        job_id = job.id
        item_id = item.id

    detail_response = client.get(f"/scraping/libby/jobs/{job_id}")

    assert detail_response.status_code == 200
    assert "No progress parsed" in detail_response.text
    assert "Retry" in detail_response.text

    response = client.post(f"/scraping/libby/jobs/{job_id}/items/{item_id}/requeue", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        item = db.get(ScrapeJobItem, item_id)
        progress = db.get(BookProgress, book_id)
        assert job is not None
        assert item is not None
        assert progress is not None
        assert job.status == "pending"
        assert job.finished_at is None
        assert item.status == "queued"
        assert progress.last_scraped_borrowed_at is None


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
    assert "Delay between pages" in response.text
    assert "5-15 seconds, randomized" in response.text
    assert "Automatic retries" in response.text
    assert "data/scraped/test/libby" in response.text
    assert f'action="/scraping/libby/jobs/{job_id}/cancel"' in response.text


def test_start_libby_scrape_job_requires_admin_login() -> None:
    client, session_factory = make_scraping_client()
    job_id = add_scrape_job(session_factory, status="pending", with_items=True)

    response = client.post(f"/scraping/libby/jobs/{job_id}/start", follow_redirects=False)

    assert response.status_code == 403


def test_start_libby_scrape_job_marks_pending_job_running_with_safety_summary() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    job_id = add_scrape_job(session_factory, status="pending", with_items=True)

    def fake_runner(db: Session, *, job: ScrapeJob, profile_dir: str, scraped_dir: str) -> dict[str, int]:
        assert profile_dir == "data/browser/test-libby-profile"
        assert scraped_dir == "data/scraped/test"
        return {"succeeded": 1, "failed": 0, "skipped": 0}

    from app.api import scraping

    original_runner = scraping.libby_scrape_runner.run_libby_scrape_job
    scraping.libby_scrape_runner.run_libby_scrape_job = fake_runner
    try:
        response = client.post(f"/scraping/libby/jobs/{job_id}/start", follow_redirects=False)
    finally:
        scraping.libby_scrape_runner.run_libby_scrape_job = original_runner

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/scraping/libby/jobs/{job_id}?")
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "completed"
        assert job.started_at is not None
        assert job.finished_at is not None
        assert job.summary["automatic_retries"] is False
        assert job.summary["run"] == {"succeeded": 1, "failed": 0, "skipped": 0}
        assert job.summary["safety"] == {
            "min_delay_seconds": 5,
            "max_delay_seconds": 15,
            "page_load_timeout_ms": 30000,
            "selector_timeout_ms": 10000,
            "max_attempts_per_run": 1,
        }


def test_start_libby_scrape_job_marks_running_items_failed_on_runner_crash() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    job_id = add_scrape_job(session_factory, status="pending", with_items=True)

    def crashing_runner(db: Session, *, job: ScrapeJob, profile_dir: str, scraped_dir: str) -> dict[str, int]:
        item = job.items[0]
        item.status = "running"
        db.flush()
        raise RuntimeError("Browser driver disconnected")

    from app.api import scraping

    original_runner = scraping.libby_scrape_runner.run_libby_scrape_job
    scraping.libby_scrape_runner.run_libby_scrape_job = crashing_runner
    try:
        response = client.post(f"/scraping/libby/jobs/{job_id}/start", follow_redirects=False)
    finally:
        scraping.libby_scrape_runner.run_libby_scrape_job = original_runner

    assert response.status_code == 303
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "failed"
        item = db.query(ScrapeJobItem).filter_by(job_id=job_id).one()
        assert item.status == "failed"
        assert item.error_code == "RuntimeError"
        assert item.error_message == "Browser driver disconnected"


def test_libby_scrape_job_allows_failed_item_retry_or_skip_after_mixed_run() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    first_book_id = add_libby_book(session_factory, title="Mixed Success Book", libby_title_id="mixed-success")
    second_book_id = add_libby_book(session_factory, title="Mixed Failed Book", libby_title_id="mixed-failed")
    with session_factory() as db:
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="pending")
        db.add(job)
        db.flush()
        db.add_all(
            [
                ScrapeJobItem(job_id=job.id, book_id=first_book_id, status="queued"),
                ScrapeJobItem(job_id=job.id, book_id=second_book_id, status="queued"),
            ]
        )
        db.commit()
        job_id = job.id

    def mixed_runner(db: Session, *, job: ScrapeJob, profile_dir: str, scraped_dir: str) -> dict[str, int]:
        items = sorted(job.items, key=lambda value: value.id)
        items[0].status = "succeeded"
        items[1].status = "failed"
        items[1].error_code = "ValueError"
        items[1].error_message = "No parseable progress."
        return {"succeeded": 1, "failed": 1, "skipped": 0}

    from app.api import scraping

    original_runner = scraping.libby_scrape_runner.run_libby_scrape_job
    scraping.libby_scrape_runner.run_libby_scrape_job = mixed_runner
    try:
        response = client.post(f"/scraping/libby/jobs/{job_id}/start", follow_redirects=False)
    finally:
        scraping.libby_scrape_runner.run_libby_scrape_job = original_runner

    assert response.status_code == 303
    detail_response = client.get(f"/scraping/libby/jobs/{job_id}")
    assert detail_response.status_code == 200
    assert "Mixed Success Book" in detail_response.text
    assert "Mixed Failed Book" in detail_response.text
    assert "No parseable progress." in detail_response.text
    assert "Retry" in detail_response.text
    assert "Skip" in detail_response.text

    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "completed"
        assert job.summary["run"] == {"succeeded": 1, "failed": 1, "skipped": 0}
        assert {item.status for item in job.items} == {"succeeded", "failed"}


def test_start_libby_scrape_job_does_not_start_completed_job() -> None:
    client, session_factory = make_scraping_client()
    client.post("/admin/login", data={"password": "secret"})
    job_id = add_scrape_job(session_factory, status="completed", with_items=True)

    response = client.post(f"/scraping/libby/jobs/{job_id}/start", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        job = db.get(ScrapeJob, job_id)
        assert job is not None
        assert job.status == "completed"


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
