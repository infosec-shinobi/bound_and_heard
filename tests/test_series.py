from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Book, BookProgress, Series, SeriesBook, User


def make_series_client(admin_password: str | None = "secret") -> tuple[TestClient, sessionmaker[Session]]:
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


def add_series(
    session_factory: sessionmaker[Session],
    *,
    name: str,
    status: str = "active",
    wants_to_continue: str = "yes",
    description: str | None = None,
) -> Series:
    with session_factory() as db:
        series = Series(
            user_id=DEFAULT_LOCAL_USER_ID,
            name=name,
            status=status,
            wants_to_continue=wants_to_continue,
            description=description,
        )
        db.add(series)
        db.commit()
        db.refresh(series)
        return series


def add_book(
    session_factory: sessionmaker[Session],
    *,
    title: str,
    author: str | None,
    status: str = "started",
) -> Book:
    with session_factory() as db:
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title=title,
            primary_author_name=author,
            format="ebook",
            status=status,
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        return book


def add_series_entry(
    session_factory: sessionmaker[Session],
    series_id: int,
    *,
    position: float,
    book_id: int | None = None,
    planned_title: str | None = None,
    planned_author_name: str | None = None,
) -> None:
    with session_factory() as db:
        db.add(
            SeriesBook(
                series_id=series_id,
                book_id=book_id,
                position=position,
                planned_title=planned_title,
                planned_author_name=planned_author_name,
                planned_format="ebook" if book_id is None else None,
            )
        )
        db.commit()


def test_series_page_shows_empty_state_for_read_only_user() -> None:
    client, _ = make_series_client(admin_password=None)

    response = client.get("/series")

    assert response.status_code == 200
    assert "No series found" in response.text
    assert "Read-only mode" in response.text
    assert "Set BOUND_AND_HEARD_ADMIN_PASSWORD to enable write actions." in response.text


def test_series_page_lists_status_progress_and_next_unread() -> None:
    client, session_factory = make_series_client()
    series = add_series(
        session_factory,
        name="Wayfarers",
        status="active",
        wants_to_continue="yes",
        description="Cozy space travels",
    )
    first_book = add_book(session_factory, title="The Long Way", author="Becky Chambers", status="completed")
    second_book = add_book(session_factory, title="A Closed Orbit", author="Becky Chambers", status="started")
    add_series_entry(session_factory, series.id, position=1, book_id=first_book.id)
    add_series_entry(session_factory, series.id, position=2, book_id=second_book.id)
    add_series_entry(
        session_factory,
        series.id,
        position=3,
        planned_title="Record of a Spaceborn Few",
        planned_author_name="Becky Chambers",
    )

    response = client.get("/series")

    assert response.status_code == 200
    assert "Wayfarers" in response.text
    assert "Cozy space travels" in response.text
    assert "Active" in response.text
    assert "Yes" in response.text
    assert "1 / 3" in response.text
    assert "A Closed Orbit" in response.text
    assert "Record of a Spaceborn Few" not in response.text


def test_series_page_treats_progress_100_as_completed_for_next_unread() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Progress Series")
    first_book = add_book(session_factory, title="Progress Done", author="Author", status="started")
    second_book = add_book(session_factory, title="Progress Next", author="Author", status="started")
    add_series_entry(session_factory, series.id, position=1, book_id=first_book.id)
    add_series_entry(session_factory, series.id, position=2, book_id=second_book.id)
    with session_factory() as db:
        db.add(
            BookProgress(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=first_book.id,
                source="manual",
                progress_percent=100,
            )
        )
        db.commit()

    response = client.get("/series")

    assert response.status_code == 200
    assert "1 / 2" in response.text
    assert "Progress Next" in response.text


def test_series_page_filters_by_search_and_status() -> None:
    client, session_factory = make_series_client()
    add_series(session_factory, name="Matching Saga", status="paused")
    add_series(session_factory, name="Other Saga", status="active")

    response = client.get("/series?q=Matching&status=paused")

    assert response.status_code == 200
    assert "Matching Saga" in response.text
    assert "Other Saga" not in response.text
    assert "Paused" in response.text


def test_series_nav_link_appears_on_dashboard() -> None:
    client, _ = make_series_client()

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/series"' in response.text
