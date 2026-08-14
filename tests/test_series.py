from collections.abc import Generator
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    book_format: str = "ebook",
    status: str = "started",
    completed_on: date | None = None,
    manual_progress_percent: float | None = None,
    metadata_source: str | None = None,
) -> Book:
    with session_factory() as db:
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title=title,
            primary_author_name=author,
            format=book_format,
            status=status,
            completed_on=completed_on,
            manual_progress_percent=manual_progress_percent,
            metadata_source=metadata_source,
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
    planned_format: str = "ebook",
) -> None:
    with session_factory() as db:
        db.add(
            SeriesBook(
                series_id=series_id,
                book_id=book_id,
                position=position,
                planned_title=planned_title,
                planned_author_name=planned_author_name,
                planned_format=planned_format if book_id is None else None,
            )
        )
        db.commit()


def login_as_admin(client: TestClient) -> None:
    response = client.post("/admin/login", data={"password": "secret"})
    assert response.status_code == 200


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


def test_create_series_form_requires_admin_login() -> None:
    client, _ = make_series_client()

    response = client.get("/series/new", follow_redirects=False)

    assert response.status_code == 403
    assert "Admin login is required for write actions." in response.text


def test_create_series_form_renders_for_admin() -> None:
    client, _ = make_series_client()
    login_as_admin(client)

    response = client.get("/series/new")

    assert response.status_code == 200
    assert "Create Series" in response.text
    assert "Series name" in response.text
    assert "Want to continue?" in response.text


def test_create_series_validates_required_name_and_choices() -> None:
    client, _ = make_series_client()
    login_as_admin(client)

    response = client.post(
        "/series/new",
        data={"name": "   ", "status": "bad", "wants_to_continue": "maybe"},
    )

    assert response.status_code == 400
    assert "Series name is required." in response.text
    assert "Status is invalid." in response.text
    assert "Continuation intent is invalid." in response.text


def test_create_series_persists_and_shows_success_message() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)

    response = client.post(
        "/series/new",
        data={
            "name": " The Expanse ",
            "description": " Space politics ",
            "status": "active",
            "wants_to_continue": "yes",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/series?message=Series+created%3A+The+Expanse"
    with session_factory() as db:
        series = db.scalars(select(Series).where(Series.name == "The Expanse")).one()
        assert series.description == "Space politics"
        assert series.status == "active"
        assert series.wants_to_continue == "yes"

    follow_response = client.get(response.headers["location"])
    assert follow_response.status_code == 200
    assert "Series created: The Expanse" in follow_response.text


def test_edit_series_form_renders_existing_values_for_admin() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(
        session_factory,
        name="Old Kingdom",
        status="paused",
        wants_to_continue="unknown",
        description="Necromancer bells",
    )

    response = client.get(f"/series/{series.id}/edit")

    assert response.status_code == 200
    assert "Edit Series" in response.text
    assert "Old Kingdom" in response.text
    assert "Necromancer bells" in response.text
    assert 'value="paused" selected' in response.text


def test_update_series_validates_and_preserves_submitted_values() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Original", status="active")

    response = client.post(
        f"/series/{series.id}/edit",
        data={
            "name": "",
            "description": "Keep me visible",
            "status": "invalid",
            "wants_to_continue": "no",
        },
    )

    assert response.status_code == 400
    assert "Series name is required." in response.text
    assert "Status is invalid." in response.text
    assert "Keep me visible" in response.text


def test_update_series_persists_without_replacing_created_at() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Before", status="active", wants_to_continue="yes")
    with session_factory() as db:
        original_created_at = db.get(Series, series.id).created_at  # type: ignore[union-attr]

    response = client.post(
        f"/series/{series.id}/edit",
        data={
            "name": "After",
            "description": "Updated description",
            "status": "abandoned",
            "wants_to_continue": "no",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/series?message=Series+updated%3A+After"
    with session_factory() as db:
        updated = db.get(Series, series.id)
        assert updated is not None
        assert updated.name == "After"
        assert updated.description == "Updated description"
        assert updated.status == "abandoned"
        assert updated.wants_to_continue == "no"
        assert updated.created_at == original_created_at


def test_edit_missing_series_redirects_with_error_message() -> None:
    client, _ = make_series_client()
    login_as_admin(client)

    response = client.get("/series/999/edit", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/series?error=Series+not+found."


def test_series_detail_returns_not_found_for_missing_series() -> None:
    client, _ = make_series_client()

    response = client.get("/series/999")

    assert response.status_code == 404
    assert "Series not found" in response.text
    assert "Back to Series" in response.text


def test_series_detail_shows_empty_entries_state() -> None:
    client, session_factory = make_series_client(admin_password=None)
    series = add_series(
        session_factory,
        name="Empty Series",
        status="unknown",
        wants_to_continue="unknown",
        description="No books yet",
    )

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "Empty Series" in response.text
    assert "No books or planned entries have been added" in response.text
    assert "0 / 0" in response.text
    assert "Read-only mode" in response.text


def test_series_detail_shows_metadata_ordering_and_next_unread() -> None:
    client, session_factory = make_series_client()
    series = add_series(
        session_factory,
        name="The Locked Tomb",
        status="active",
        wants_to_continue="yes",
        description="Necromancers in space",
    )
    first = add_book(
        session_factory,
        title="Gideon the Ninth",
        author="Tamsyn Muir",
        book_format="audiobook",
        status="completed",
        completed_on=date(2026, 1, 3),
        metadata_source="libby",
    )
    second = add_book(
        session_factory,
        title="Harrow the Ninth",
        author="Tamsyn Muir",
        book_format="ebook",
        status="started",
        manual_progress_percent=42,
        metadata_source="manual",
    )
    add_series_entry(session_factory, series.id, position=2, book_id=second.id)
    add_series_entry(session_factory, series.id, position=1, book_id=first.id)
    add_series_entry(
        session_factory,
        series.id,
        position=3,
        planned_title="Nona the Ninth",
        planned_author_name="Tamsyn Muir",
        planned_format="physical",
    )

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "The Locked Tomb" in response.text
    assert "Necromancers in space" in response.text
    assert "Active" in response.text
    assert "Yes" in response.text
    assert "1 / 3" in response.text
    assert "Harrow the Ninth" in response.text
    assert "Next unread" in response.text
    assert f'href="/books/{first.id}"' in response.text
    assert f'href="/books/{second.id}"' in response.text
    assert "Audiobook" in response.text
    assert "2026-01-03" in response.text
    assert "42%" in response.text
    assert "Libby" in response.text
    assert "Manual" in response.text
    assert "Nona the Ninth" in response.text
    assert "Physical" in response.text
    table_html = response.text[response.text.find("Books In Series") :]
    assert table_html.find("Gideon the Ninth") < table_html.find("Harrow the Ninth")
    assert table_html.find("Harrow the Ninth") < table_html.find("Nona the Ninth")


def test_series_detail_treats_progress_100_as_completed_before_next_unread() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Progress Detail")
    first = add_book(session_factory, title="Fully Scraped", author="Author", status="started")
    second = add_book(session_factory, title="Actual Next", author="Author", status="want_to_read")
    add_series_entry(session_factory, series.id, position=1, book_id=first.id)
    add_series_entry(session_factory, series.id, position=2, book_id=second.id)
    with session_factory() as db:
        db.add(
            BookProgress(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=first.id,
                source="scraped",
                progress_percent=100,
            )
        )
        db.commit()

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "1 / 2" in response.text
    assert "Actual Next" in response.text
    assert "Fully Scraped" in response.text
