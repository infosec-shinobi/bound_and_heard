from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Book, BookProgress, ReadingEvent, User


def make_books_client(admin_password: str | None = "secret") -> tuple[TestClient, sessionmaker[Session]]:
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


def add_book(
    session_factory: sessionmaker[Session],
    *,
    title: str,
    author: str | None,
    book_format: str = "ebook",
    status: str = "started",
    rating: float | None = None,
    manual_progress_percent: float | None = None,
    archived: bool = False,
    metadata_source: str | None = None,
    review_status: str | None = None,
    isbn10: str | None = None,
    isbn13: str | None = None,
    libby_title_id: str | None = None,
) -> Book:
    with session_factory() as db:
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title=title,
            primary_author_name=author,
            format=book_format,
            status=status,
            rating=rating,
            manual_progress_percent=manual_progress_percent,
            archived_at=datetime.now(timezone.utc) if archived else None,
            metadata_source=metadata_source,
            review_status=review_status,
            isbn10=isbn10,
            isbn13=isbn13,
            libby_title_id=libby_title_id,
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        return book


def set_review_metadata(
    session_factory: sessionmaker[Session],
    book_id: int,
    *,
    page_count: int | None = 320,
    audio_seconds: int | None = 8100,
    author: str | None = "Review Author",
    publisher: str | None = "Review Publisher",
    isbn13: str | None = "9781234567890",
    cover_url: str | None = "https://example.test/cover.jpg",
    libby_title_id: str | None = "libby-title-1",
    completed_on: datetime | None = None,
) -> None:
    with session_factory() as db:
        book = db.get(Book, book_id)
        assert book is not None
        book.page_count = page_count
        book.audio_seconds = audio_seconds
        book.primary_author_name = author
        book.publisher = publisher
        book.isbn13 = isbn13
        book.cover_url = cover_url
        book.libby_title_id = libby_title_id
        book.completed_on = completed_on.date() if completed_on else None
        db.commit()


def add_reading_event(session_factory: sessionmaker[Session], book_id: int) -> None:
    with session_factory() as db:
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book_id,
                source="libby",
                event_type="borrowed",
                event_date=datetime(2026, 6, 20, tzinfo=timezone.utc),
            )
        )
        db.commit()


def test_books_page_shows_empty_state() -> None:
    client, _ = make_books_client(admin_password=None)

    response = client.get("/books")

    assert response.status_code == 200
    assert "No books found" in response.text
    assert "Read-only mode" in response.text


def test_books_page_lists_core_book_fields() -> None:
    client, session_factory = make_books_client()
    book = add_book(
        session_factory,
        title="The Long Way",
        author="Becky Chambers",
        book_format="audiobook",
        status="completed",
        rating=4.5,
    )
    with session_factory() as db:
        db.add(
            BookProgress(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                progress_percent=100,
            )
        )
        db.commit()

    response = client.get("/books")

    assert response.status_code == 200
    assert "The Long Way" in response.text
    assert "Becky Chambers" in response.text
    assert "Audiobook" in response.text
    assert "Completed" in response.text
    assert "Missing" in response.text
    assert "4.5" in response.text
    assert "100%" in response.text


def test_books_page_hides_archived_books_by_default() -> None:
    client, session_factory = make_books_client()
    add_book(session_factory, title="Visible Book", author="Author")
    add_book(session_factory, title="Archived Book", author="Author", archived=True)

    response = client.get("/books")

    assert response.status_code == 200
    assert "Visible Book" in response.text
    assert "Archived Book" not in response.text


def test_books_page_can_include_archived_books() -> None:
    client, session_factory = make_books_client()
    add_book(session_factory, title="Archived Book", author="Author", archived=True)

    response = client.get("/books?include_archived=true")

    assert response.status_code == 200
    assert "Archived Book" in response.text
    assert "Archived" in response.text


def test_books_page_filters_by_search_status_format_and_source() -> None:
    client, session_factory = make_books_client()
    add_book(
        session_factory,
        title="Matching Book",
        author="Target Author",
        book_format="physical",
        status="completed",
        metadata_source="libby",
    )
    add_book(
        session_factory,
        title="Other Book",
        author="Someone Else",
        book_format="ebook",
        status="started",
        metadata_source="manual",
    )

    response = client.get("/books?q=Target&status=completed&format=physical&source=libby")

    assert response.status_code == 200
    assert "Matching Book" in response.text
    assert "Libby" in response.text
    assert "Other Book" not in response.text
    assert 'id="source" name="source"' in response.text
    assert 'option value="libby" selected' in response.text


def test_books_page_filters_by_missing_source() -> None:
    client, session_factory = make_books_client()
    add_book(session_factory, title="Missing Source Book", author="Author")
    add_book(session_factory, title="Manual Source Book", author="Author", metadata_source="manual")

    response = client.get("/books?source=missing")

    assert response.status_code == 200
    assert "Missing Source Book" in response.text
    assert "Manual Source Book" not in response.text
    assert 'option value="missing" selected' in response.text


def test_imported_books_review_page_is_readable_without_write_access() -> None:
    client, session_factory = make_books_client(admin_password=None)
    add_book(
        session_factory,
        title="Readonly Review Book",
        author="Libby Author",
        metadata_source="libby",
    )

    response = client.get("/books/review")

    assert response.status_code == 200
    assert "Imported Books Needing Review" in response.text
    assert "Readonly Review Book" in response.text
    assert "Read-only mode" in response.text


def test_imported_books_review_page_lists_libby_books_needing_review() -> None:
    client, session_factory = make_books_client()
    book = add_book(
        session_factory,
        title="Libby Review Book",
        author="Review Author",
        book_format="audiobook",
        status="completed",
        manual_progress_percent=100,
        metadata_source="libby",
    )
    with session_factory() as db:
        db_book = db.get(Book, book.id)
        assert db_book is not None
        db_book.page_count = 320
        db_book.audio_seconds = 8100
        db_book.completed_on = datetime(2026, 6, 20, tzinfo=timezone.utc).date()
        db_book.libby_title_id = "libby-1"
        db.commit()

    response = client.get("/books/review")

    assert response.status_code == 200
    assert "Libby Review Book" in response.text
    assert "Review Author" in response.text
    assert "Audiobook" in response.text
    assert "Completed" in response.text
    assert f'action="/books/{book.id}/review/status"' not in response.text
    assert "100%" in response.text
    assert "320" in response.text
    assert "2 hr 15 min" in response.text
    assert "2026-06-20" in response.text
    assert "Title ID libby-1" in response.text
    assert f'href="/books/{book.id}"' in response.text


def test_imported_books_review_page_shows_quick_status_form_after_admin_login() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Status Review Book", author="Author", metadata_source="libby")
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/books/review?missing_page_count=true")

    assert response.status_code == 200
    assert f'action="/books/{book.id}/review/status"' in response.text
    assert 'name="return_to" value="/books/review?missing_page_count=true"' in response.text
    assert 'option value="want_to_read"' in response.text
    assert 'option value="borrowed"' in response.text
    assert 'option value="started" selected' in response.text
    assert 'option value="completed"' in response.text
    assert 'option value="abandoned"' in response.text
    assert 'option value="unknown"' in response.text


def test_quick_status_update_requires_admin_login() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Protected Status", author="Author", metadata_source="libby")

    response = client.post(
        f"/books/{book.id}/review/status",
        data={"status": "completed", "return_to": "/books/review?missing_page_count=true"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    with session_factory() as db:
        unchanged = db.get(Book, book.id)
        assert unchanged is not None
        assert unchanged.status == "started"


def test_quick_status_update_changes_status_creates_event_and_returns_to_filter() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Quick Status", author="Author", metadata_source="libby")
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        f"/books/{book.id}/review/status",
        data={"status": "completed", "return_to": "/books/review?missing_page_count=true"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/books/review?missing_page_count=true"
    with session_factory() as db:
        updated = db.get(Book, book.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.metadata_source == "libby"
        event = db.query(ReadingEvent).filter_by(book_id=book.id, event_type="manually_corrected").one()
        assert event.raw_data == {"changed_fields": {"status": {"from": "started", "to": "completed"}}}


def test_quick_status_update_rejects_invalid_status() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Invalid Status", author="Author", metadata_source="libby")
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        f"/books/{book.id}/review/status",
        data={"status": "not-valid", "return_to": "https://example.test/unsafe"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/books/review"
    with session_factory() as db:
        unchanged = db.get(Book, book.id)
        assert unchanged is not None
        assert unchanged.status == "started"
        assert db.query(ReadingEvent).filter_by(book_id=book.id, event_type="manually_corrected").count() == 0


def test_imported_books_review_page_excludes_non_review_books() -> None:
    client, session_factory = make_books_client()
    add_book(session_factory, title="Needs Review", author="Author", metadata_source="libby")
    add_book(session_factory, title="Manual Book", author="Author", metadata_source="manual")
    add_book(
        session_factory,
        title="Reviewed Book",
        author="Author",
        metadata_source="libby",
        review_status="reviewed",
    )
    add_book(
        session_factory,
        title="Ignored Book",
        author="Author",
        metadata_source="libby",
        review_status="ignored",
    )
    add_book(
        session_factory,
        title="Duplicate Candidate",
        author="Author",
        metadata_source="libby",
        review_status="duplicate_candidate",
    )
    add_book(
        session_factory,
        title="Archived Imported",
        author="Author",
        metadata_source="libby",
        archived=True,
    )

    response = client.get("/books/review")

    assert response.status_code == 200
    assert "Needs Review" in response.text
    assert "Duplicate Candidate" in response.text
    assert "Manual Book" not in response.text
    assert "Reviewed Book" not in response.text
    assert "Ignored Book" not in response.text
    assert "Archived Imported" not in response.text


def test_imported_books_review_page_shows_empty_state() -> None:
    client, _ = make_books_client(admin_password=None)

    response = client.get("/books/review")

    assert response.status_code == 200
    assert "No imported books need review" in response.text


@pytest.mark.parametrize(
    ("query_param", "missing_field"),
    [
        ("missing_page_count", "page_count"),
        ("missing_audio_duration", "audio_seconds"),
        ("missing_author", "author"),
        ("missing_publisher", "publisher"),
        ("missing_isbn", "isbn13"),
        ("missing_cover_url", "cover_url"),
    ],
)
def test_imported_books_review_page_filters_missing_core_metadata(
    query_param: str,
    missing_field: str,
) -> None:
    client, session_factory = make_books_client()
    matching = add_book(
        session_factory,
        title=f"Missing {missing_field}",
        author="Review Author",
        metadata_source="libby",
    )
    complete = add_book(
        session_factory,
        title="Complete Metadata",
        author="Review Author",
        metadata_source="libby",
    )
    set_review_metadata(session_factory, complete.id)

    missing_values = {
        "page_count": {"page_count": None},
        "audio_seconds": {"audio_seconds": None},
        "author": {"author": None},
        "publisher": {"publisher": None},
        "isbn13": {"isbn13": None},
        "cover_url": {"cover_url": None},
    }
    set_review_metadata(session_factory, matching.id, **missing_values[missing_field])

    response = client.get(f"/books/review?{query_param}=true")

    assert response.status_code == 200
    assert f"Missing {missing_field}" in response.text
    assert "Complete Metadata" not in response.text
    assert f'id="filter-{query_param}" checked' in response.text


def test_imported_books_review_page_combines_missing_metadata_filters() -> None:
    client, session_factory = make_books_client()
    matching = add_book(
        session_factory,
        title="Missing Pages And Author",
        author="Review Author",
        metadata_source="libby",
    )
    missing_pages_only = add_book(
        session_factory,
        title="Missing Pages Only",
        author="Review Author",
        metadata_source="libby",
    )
    missing_author_only = add_book(
        session_factory,
        title="Missing Author Only",
        author="Review Author",
        metadata_source="libby",
    )

    set_review_metadata(session_factory, matching.id, page_count=None, author=None)
    set_review_metadata(session_factory, missing_pages_only.id, page_count=None)
    set_review_metadata(session_factory, missing_author_only.id, author=None)

    response = client.get("/books/review?missing_page_count=true&missing_author=true")

    assert response.status_code == 200
    assert "Missing Pages And Author" in response.text
    assert "Missing Pages Only" not in response.text
    assert "Missing Author Only" not in response.text
    assert 'id="filter-missing_page_count" checked' in response.text
    assert 'id="filter-missing_author" checked' in response.text


@pytest.mark.parametrize(
    ("query_param", "matching_title", "matching_book_kwargs", "matching_metadata_kwargs"),
    [
        ("unknown_format", "Unknown Format", {"book_format": "unknown"}, {}),
        ("unknown_status", "Unknown Status", {"status": "unknown"}, {}),
        ("missing_libby_title_id", "Missing Libby Title ID", {}, {"libby_title_id": None}),
        ("fallback_title", "Untitled Libby Book", {}, {}),
        (
            "completed_without_completion_date",
            "Completed Without Date",
            {"status": "completed"},
            {"completed_on": None},
        ),
        (
            "progress_status_mismatch",
            "Started At 100 Percent",
            {"status": "started", "manual_progress_percent": 100},
            {},
        ),
    ],
)
def test_imported_books_review_page_filters_suspicious_metadata(
    query_param: str,
    matching_title: str,
    matching_book_kwargs: dict[str, object],
    matching_metadata_kwargs: dict[str, object],
) -> None:
    client, session_factory = make_books_client()
    matching = add_book(
        session_factory,
        title=matching_title,
        author="Review Author",
        metadata_source="libby",
        **matching_book_kwargs,
    )
    safe_status = "completed" if query_param == "completed_without_completion_date" else "started"
    safe_completed_on = (
        datetime(2026, 6, 20, tzinfo=timezone.utc)
        if query_param == "completed_without_completion_date"
        else None
    )
    safe = add_book(
        session_factory,
        title="Safe Review Book",
        author="Review Author",
        status=safe_status,
        manual_progress_percent=50,
        metadata_source="libby",
    )
    set_review_metadata(session_factory, matching.id, **matching_metadata_kwargs)
    set_review_metadata(session_factory, safe.id, completed_on=safe_completed_on)

    response = client.get(f"/books/review?{query_param}=true")

    assert response.status_code == 200
    assert matching_title in response.text
    assert "Safe Review Book" not in response.text
    assert f'id="filter-{query_param}" checked' in response.text


def test_imported_books_review_page_filters_books_without_reading_events() -> None:
    client, session_factory = make_books_client()
    matching = add_book(
        session_factory,
        title="No Reading Events",
        author="Review Author",
        metadata_source="libby",
    )
    safe = add_book(
        session_factory,
        title="Has Reading Event",
        author="Review Author",
        metadata_source="libby",
    )
    set_review_metadata(session_factory, matching.id)
    set_review_metadata(session_factory, safe.id)
    add_reading_event(session_factory, safe.id)

    response = client.get("/books/review?no_reading_events=true")

    assert response.status_code == 200
    assert "No Reading Events" in response.text
    assert "Has Reading Event" not in response.text
    assert 'id="filter-no_reading_events" checked' in response.text


@pytest.mark.parametrize(
    ("matching_kwargs", "duplicate_kwargs", "reason"),
    [
        (
            {"libby_title_id": "libby-duplicate-1", "book_format": "ebook"},
            {"libby_title_id": "libby-duplicate-1", "book_format": "ebook"},
            "Same Libby title ID and format: libby-duplicate-1 / ebook",
        ),
        (
            {"title": "Duplicate Title", "author": "Same Author", "book_format": "ebook"},
            {"title": " duplicate   title ", "author": "same author", "book_format": "ebook"},
            "Same normalized title, author, and format",
        ),
        (
            {"isbn13": "9781234567890", "book_format": "ebook"},
            {"isbn13": "9781234567890", "book_format": "ebook"},
            "Same ISBN and format: 9781234567890 / ebook",
        ),
    ],
)
def test_imported_books_review_page_filters_duplicate_candidates(
    matching_kwargs: dict[str, object],
    duplicate_kwargs: dict[str, object],
    reason: str,
) -> None:
    client, session_factory = make_books_client()
    matching = add_book(
        session_factory,
        title=str(matching_kwargs.pop("title", "Duplicate Match")),
        author=matching_kwargs.pop("author", "Review Author"),
        metadata_source="libby",
        **matching_kwargs,
    )
    add_book(
        session_factory,
        title=str(duplicate_kwargs.pop("title", "Existing Duplicate")),
        author=duplicate_kwargs.pop("author", "Review Author"),
        metadata_source="manual",
        **duplicate_kwargs,
    )
    add_book(session_factory, title="Unique Review Book", author="Review Author", metadata_source="libby")

    response = client.get("/books/review?duplicate_candidate=true")

    assert response.status_code == 200
    assert matching.title in response.text
    assert "Unique Review Book" not in response.text
    assert reason in response.text
    assert 'id="filter-duplicate_candidate" checked' in response.text


def test_imported_books_review_page_keeps_title_author_duplicates_format_specific() -> None:
    client, session_factory = make_books_client()
    add_book(
        session_factory,
        title="Format Specific",
        author="Same Author",
        book_format="ebook",
        metadata_source="libby",
    )
    add_book(
        session_factory,
        title="format specific",
        author="same author",
        book_format="audiobook",
        metadata_source="manual",
    )

    response = client.get("/books/review?duplicate_candidate=true")

    assert response.status_code == 200
    assert "Format Specific" not in response.text
    assert "No imported books need review" in response.text


@pytest.mark.parametrize(
    ("matching_kwargs", "duplicate_kwargs"),
    [
        (
            {"libby_title_id": "libby-related-1", "book_format": "ebook"},
            {"libby_title_id": "libby-related-1", "book_format": "audiobook"},
        ),
        (
            {"isbn13": "9781234567890", "book_format": "ebook"},
            {"isbn13": "9781234567890", "book_format": "audiobook"},
        ),
    ],
)
def test_imported_books_review_page_keeps_identifier_matches_format_specific(
    matching_kwargs: dict[str, object],
    duplicate_kwargs: dict[str, object],
) -> None:
    client, session_factory = make_books_client()
    add_book(
        session_factory,
        title="Related Format",
        author="Same Author",
        metadata_source="libby",
        **matching_kwargs,
    )
    add_book(
        session_factory,
        title="Related Format",
        author="Same Author",
        metadata_source="manual",
        **duplicate_kwargs,
    )

    response = client.get("/books/review?duplicate_candidate=true")

    assert response.status_code == 200
    assert "Related Format" not in response.text
    assert "No imported books need review" in response.text


def test_review_nav_link_is_present() -> None:
    client, _ = make_books_client(admin_password=None)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/books/review"' in response.text


def test_add_book_form_is_protected() -> None:
    client, _ = make_books_client()

    response = client.get("/books/new")

    assert response.status_code == 403


def test_add_book_form_is_available_after_admin_login() -> None:
    client, _ = make_books_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/books/new")

    assert response.status_code == 200
    assert "Add Book" in response.text
    assert "Create Book" in response.text


def test_create_book_saves_supported_fields_and_redirects_to_detail() -> None:
    client, session_factory = make_books_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/books/new",
        data={
            "title": "A Psalm for the Wild-Built",
            "subtitle": "Monk and Robot",
            "primary_author_name": "Becky Chambers",
            "isbn": "978-1250236210",
            "format": "audiobook",
            "status": "started",
            "rating": "4.5",
            "notes": "Cozy robots.",
            "started_on": "2026-06-01",
            "page_count": "160",
            "audio_hours": "4.25",
            "manual_progress_percent": "35",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/books/")

    with session_factory() as db:
        book = db.query(Book).filter_by(title="A Psalm for the Wild-Built").one()
        assert book.subtitle == "Monk and Robot"
        assert book.primary_author_name == "Becky Chambers"
        assert book.isbn13 == "9781250236210"
        assert book.isbn10 is None
        assert book.format == "audiobook"
        assert book.status == "started"
        assert book.rating == 4.5
        assert book.notes == "Cozy robots."
        assert book.page_count == 160
        assert book.audio_seconds == 15300
        assert book.manual_progress_percent == 35


def test_create_book_creates_initial_reading_events() -> None:
    client, session_factory = make_books_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/books/new",
        data={
            "title": "Finished Book",
            "format": "ebook",
            "status": "completed",
            "started_on": "2026-06-01",
            "completed_on": "2026-06-03",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        book = db.query(Book).filter_by(title="Finished Book").one()
        events = db.query(ReadingEvent).filter_by(book_id=book.id).order_by(ReadingEvent.event_type).all()

    assert [event.event_type for event in events] == ["manually_completed", "started"]
    completed_event = next(event for event in events if event.event_type == "manually_completed")
    assert completed_event.progress_percent == 100


def test_create_book_renders_validation_errors() -> None:
    client, session_factory = make_books_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/books/new",
        data={
            "title": " ",
            "format": "ebook",
            "status": "started",
            "isbn": "123",
            "rating": "9",
            "manual_progress_percent": "120",
        },
    )

    assert response.status_code == 400
    assert "Title is required." in response.text
    assert "ISBN must be a valid ISBN-10 or ISBN-13." in response.text
    assert "Rating must be no more than 5." in response.text
    assert "Manual progress percent must be no more than 100." in response.text
    with session_factory() as db:
        assert db.query(Book).count() == 0


def test_book_detail_shows_metadata_progress_stats_and_events() -> None:
    client, session_factory = make_books_client()
    book = add_book(
        session_factory,
        title="Detail Book",
        author="Detail Author",
        book_format="audiobook",
        status="completed",
        rating=5,
        manual_progress_percent=40,
    )
    with session_factory() as db:
        db_book = db.get(Book, book.id)
        assert db_book is not None
        db_book.subtitle = "The Subtitle"
        db_book.notes = "Line one\nLine two"
        db_book.isbn10 = "123456789X"
        db_book.page_count = 320
        db_book.audio_seconds = 3660
        db.add(
            BookProgress(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                progress_percent=100,
            )
        )
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                event_type="manually_completed",
                event_date=datetime(2026, 6, 3, tzinfo=timezone.utc),
                progress_percent=100,
            )
        )
        db.commit()

    response = client.get(f"/books/{book.id}")

    assert response.status_code == 200
    assert "Detail Book" in response.text
    assert "The Subtitle" in response.text
    assert "Detail Author" in response.text
    assert "Audiobook" in response.text
    assert "Completed" in response.text
    assert "5.0 / 5" in response.text
    assert "123456789X" in response.text
    assert "100%" in response.text
    assert "320" in response.text
    assert "1 hr 1 min" in response.text
    assert "Line one" in response.text
    assert "Manually Completed" in response.text
    assert "2026-06-03" in response.text


def test_book_detail_shows_archived_state() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Archived Detail", author="Author", archived=True)

    response = client.get(f"/books/{book.id}")

    assert response.status_code == 200
    assert "Archived Detail" in response.text
    assert "This book is archived" in response.text


def test_book_detail_returns_404_for_missing_book() -> None:
    client, _ = make_books_client()

    response = client.get("/books/999")

    assert response.status_code == 404
    assert "Book not found" in response.text


def test_book_detail_edit_and_archive_actions_are_protected() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Protected Book", author="Author")

    edit_response = client.get(f"/books/{book.id}/edit")
    archive_response = client.post(f"/books/{book.id}/archive")

    assert edit_response.status_code == 403
    assert archive_response.status_code == 403


def test_book_detail_edit_form_is_available_after_login() -> None:
    client, session_factory = make_books_client()
    book = add_book(
        session_factory,
        title="Editable Book",
        author="Author",
        book_format="ebook",
        status="started",
        rating=3,
        manual_progress_percent=25,
    )
    client.post("/admin/login", data={"password": "secret"})

    edit_response = client.get(f"/books/{book.id}/edit")

    assert edit_response.status_code == 200
    assert "Edit Book" in edit_response.text
    assert "Editable Book" in edit_response.text
    assert "Save Changes" in edit_response.text


def test_update_book_changes_fields_and_redirects_to_detail() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Old Title", author="Old Author")
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        f"/books/{book.id}/edit",
        data={
            "title": "New Title",
            "subtitle": "New Subtitle",
            "primary_author_name": "New Author",
            "isbn": "123456789X",
            "format": "physical",
            "status": "want_to_read",
            "rating": "4.2",
            "notes": "Updated notes.",
            "started_on": "2026-06-01",
            "page_count": "300",
            "audio_hours": "",
            "manual_progress_percent": "10",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{book.id}"
    with session_factory() as db:
        updated = db.get(Book, book.id)
        assert updated is not None
        assert updated.title == "New Title"
        assert updated.subtitle == "New Subtitle"
        assert updated.primary_author_name == "New Author"
        assert updated.isbn10 == "123456789X"
        assert updated.isbn13 is None
        assert updated.format == "physical"
        assert updated.status == "want_to_read"
        assert updated.rating == 4.2
        assert updated.notes == "Updated notes."
        assert updated.page_count == 300
        assert updated.audio_seconds is None
        assert updated.manual_progress_percent == 10


def test_update_book_creates_correction_event_for_status_progress_or_completion_changes() -> None:
    client, session_factory = make_books_client()
    book = add_book(
        session_factory,
        title="Corrected Book",
        author="Author",
        status="started",
        manual_progress_percent=20,
    )
    with session_factory() as db:
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                event_type="started",
                event_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            )
        )
        db.commit()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        f"/books/{book.id}/edit",
        data={
            "title": "Corrected Book",
            "primary_author_name": "Author",
            "format": "ebook",
            "status": "completed",
            "completed_on": "2026-06-05",
            "manual_progress_percent": "100",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        events = db.query(ReadingEvent).filter_by(book_id=book.id).order_by(ReadingEvent.id).all()

    assert [event.event_type for event in events] == ["started", "manually_corrected"]
    correction = events[-1]
    assert correction.progress_percent == 100
    assert correction.raw_data == {
        "changed_fields": {
            "status": {"from": "started", "to": "completed"},
            "completed_on": {"from": None, "to": "2026-06-05"},
            "manual_progress_percent": {"from": 20.0, "to": 100.0},
        }
    }


def test_update_book_does_not_delete_existing_event_history() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="History Book", author="Author")
    with session_factory() as db:
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                event_type="started",
                event_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            )
        )
        db.commit()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        f"/books/{book.id}/edit",
        data={
            "title": "History Book Renamed",
            "primary_author_name": "Author",
            "format": "ebook",
            "status": "started",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        events = db.query(ReadingEvent).filter_by(book_id=book.id).all()

    assert len(events) == 1
    assert events[0].event_type == "started"


def test_update_book_renders_validation_errors() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Validation Book", author="Author")
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        f"/books/{book.id}/edit",
        data={
            "title": " ",
            "format": "ebook",
            "status": "started",
            "completed_on": "bad-date",
        },
    )

    assert response.status_code == 400
    assert "Title is required." in response.text
    assert "Completed date must be a valid date." in response.text
    with session_factory() as db:
        unchanged = db.get(Book, book.id)
        assert unchanged is not None
        assert unchanged.title == "Validation Book"


def test_archive_book_sets_archived_at_and_redirects() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Archive Me", author="Author")
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(f"/books/{book.id}/archive", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{book.id}"
    with session_factory() as db:
        archived = db.get(Book, book.id)
        assert archived is not None
        assert archived.archived_at is not None


def test_archived_book_is_hidden_by_default_but_visible_with_filter() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Hidden Archive", author="Author")
    client.post("/admin/login", data={"password": "secret"})
    client.post(f"/books/{book.id}/archive")

    default_response = client.get("/books")
    filtered_response = client.get("/books?include_archived=true")

    assert default_response.status_code == 200
    assert "Hidden Archive" not in default_response.text
    assert filtered_response.status_code == 200
    assert "Hidden Archive" in filtered_response.text
    assert "Archived" in filtered_response.text


def test_archive_preserves_book_data_events_and_progress() -> None:
    client, session_factory = make_books_client()
    book = add_book(
        session_factory,
        title="Preserved Book",
        author="Author",
        rating=4.5,
        manual_progress_percent=50,
    )
    with session_factory() as db:
        db_book = db.get(Book, book.id)
        assert db_book is not None
        db_book.notes = "Keep this note."
        db_book.libby_title_id = "libby-123"
        db_book.libby_share_url = "https://share.libbyapp.com/title/123"
        db.add(
            BookProgress(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                progress_percent=50,
            )
        )
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                event_type="progress_seen",
                event_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                progress_percent=50,
            )
        )
        db.commit()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(f"/books/{book.id}/archive", follow_redirects=False)

    assert response.status_code == 303
    with session_factory() as db:
        archived = db.get(Book, book.id)
        assert archived is not None
        assert archived.archived_at is not None
        assert archived.notes == "Keep this note."
        assert archived.rating == 4.5
        assert archived.manual_progress_percent == 50
        assert archived.libby_title_id == "libby-123"
        assert archived.libby_share_url == "https://share.libbyapp.com/title/123"
        assert db.query(BookProgress).filter_by(book_id=book.id).count() == 1
        assert db.query(ReadingEvent).filter_by(book_id=book.id).count() == 1


def test_restore_book_clears_archived_at_and_redirects() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Restore Me", author="Author", archived=True)
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(f"/books/{book.id}/restore", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{book.id}"
    with session_factory() as db:
        restored = db.get(Book, book.id)
        assert restored is not None
        assert restored.archived_at is None


def test_archived_book_detail_shows_restore_action_after_login() -> None:
    client, session_factory = make_books_client()
    book = add_book(session_factory, title="Restorable Detail", author="Author", archived=True)
    client.post("/admin/login", data={"password": "secret"})

    response = client.get(f"/books/{book.id}")

    assert response.status_code == 200
    assert "Restore" in response.text
    assert f'action="/books/{book.id}/restore"' in response.text
