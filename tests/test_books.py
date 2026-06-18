from collections.abc import Generator
from datetime import datetime, timezone

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
    author: str,
    book_format: str = "ebook",
    status: str = "started",
    rating: float | None = None,
    manual_progress_percent: float | None = None,
    archived: bool = False,
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
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        return book


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


def test_books_page_filters_by_search_status_and_format() -> None:
    client, session_factory = make_books_client()
    add_book(
        session_factory,
        title="Matching Book",
        author="Target Author",
        book_format="physical",
        status="completed",
    )
    add_book(
        session_factory,
        title="Other Book",
        author="Someone Else",
        book_format="ebook",
        status="started",
    )

    response = client.get("/books?q=Target&status=completed&format=physical")

    assert response.status_code == 200
    assert "Matching Book" in response.text
    assert "Other Book" not in response.text


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
            "rating": "9",
            "manual_progress_percent": "120",
        },
    )

    assert response.status_code == 400
    assert "Title is required." in response.text
    assert "Rating must be no more than 5." in response.text
    assert "Manual progress percent must be no more than 100." in response.text
    with session_factory() as db:
        assert db.query(Book).count() == 0
