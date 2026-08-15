from collections.abc import Generator
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Book, BookProgress, ReadingEvent, Series, SeriesBook, User


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


def add_reading_event(session_factory: sessionmaker[Session], book_id: int) -> None:
    with session_factory() as db:
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book_id,
                source="manual",
                event_type="started",
                event_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
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


def test_series_detail_shows_assign_existing_book_form_for_admin() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Assignable")
    add_book(
        session_factory,
        title="Searchable Book",
        author="Search Author",
        book_format="audiobook",
        metadata_source="libby",
    )
    add_book(session_factory, title="Hidden Book", author="Other", metadata_source="manual")

    response = client.get(f"/series/{series.id}?book_q=Search")

    assert response.status_code == 200
    assert "Assign Existing Book" in response.text
    assert "Searchable Book - Search Author - Audiobook - Libby" in response.text
    assert "Hidden Book" not in response.text


def test_assign_existing_book_requires_admin_login() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Protected")
    book = add_book(session_factory, title="Protected Book", author="Author")

    response = client.post(
        f"/series/{series.id}/books/add",
        data={"book_id": str(book.id), "position": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert "Admin login is required for write actions." in response.text


def test_assign_existing_book_to_series_persists_position() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Assignment")
    book = add_book(session_factory, title="Assigned Book", author="Author")

    response = client.post(
        f"/series/{series.id}/books/add",
        data={"book_id": str(book.id), "position": "2.5"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?message=Added+Assigned+Book+to+this+series."
    with session_factory() as db:
        entry = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).one()
        assert entry.book_id == book.id
        assert entry.position == 2.5


def test_assign_existing_book_rejects_duplicate_assignment() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Duplicates")
    book = add_book(session_factory, title="Duplicate Book", author="Author")
    add_series_entry(session_factory, series.id, position=1, book_id=book.id)

    response = client.post(
        f"/series/{series.id}/books/add",
        data={"book_id": str(book.id), "position": "2"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?error=Duplicate+Book+is+already+in+this+series."
    with session_factory() as db:
        entries = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).all()
        assert len(entries) == 1
        assert entries[0].position == 1


def test_assign_existing_book_rejects_invalid_position() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Bad Position")
    book = add_book(session_factory, title="Position Book", author="Author")

    response = client.post(
        f"/series/{series.id}/books/add",
        data={"book_id": str(book.id), "position": "first"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?error=Position+must+be+a+number."


def test_update_existing_series_book_position_changes_order() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Reorder")
    first = add_book(session_factory, title="First Book", author="Author")
    second = add_book(session_factory, title="Second Book", author="Author")
    add_series_entry(session_factory, series.id, position=1, book_id=first.id)
    add_series_entry(session_factory, series.id, position=2, book_id=second.id)
    with session_factory() as db:
        second_entry = db.scalars(
            select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.book_id == second.id)
        ).one()

    response = client.post(
        f"/series/{series.id}/entries/{second_entry.id}/position",
        data={"position": "0.5"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    follow_response = client.get(response.headers["location"])
    table_html = follow_response.text[follow_response.text.find("Books In Series") :]
    assert table_html.find("Second Book") < table_html.find("First Book")


def test_remove_existing_book_from_series_preserves_book_history_and_progress() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Removal")
    book = add_book(session_factory, title="Preserved Book", author="Author", metadata_source="libby")
    add_series_entry(session_factory, series.id, position=1, book_id=book.id)
    add_reading_event(session_factory, book.id)
    with session_factory() as db:
        db.add(
            BookProgress(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                progress_percent=55,
            )
        )
        db.commit()
        entry = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).one()

    response = client.post(
        f"/series/{series.id}/entries/{entry.id}/remove",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?message=Removed+book+from+this+series."
    with session_factory() as db:
        assert db.get(Book, book.id) is not None
        assert db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).all() == []
        assert db.scalars(select(ReadingEvent).where(ReadingEvent.book_id == book.id)).one() is not None
        progress = db.scalars(select(BookProgress).where(BookProgress.book_id == book.id)).one()
        assert progress.progress_percent == 55
        assert db.get(Book, book.id).metadata_source == "libby"  # type: ignore[union-attr]


def test_series_detail_shows_add_planned_book_form_for_admin() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Planned UI")

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "Add Planned Book" in response.text
    assert "Add Planned" in response.text
    assert "Audiobook" in response.text


def test_add_planned_series_entry_requires_admin_login() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Protected Planned")

    response = client.post(
        f"/series/{series.id}/planned/add",
        data={"planned_title": "Future Book", "planned_format": "ebook", "position": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert "Admin login is required for write actions." in response.text


def test_add_planned_series_entry_persists_without_book_record() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Planned Add")

    response = client.post(
        f"/series/{series.id}/planned/add",
        data={
            "planned_title": " Future Book ",
            "planned_author_name": " Future Author ",
            "planned_format": "physical",
            "position": "3.5",
            "notes": " Buy later ",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?message=Added+planned+book%3A+Future+Book"
    with session_factory() as db:
        entry = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).one()
        assert entry.book_id is None
        assert entry.planned_title == "Future Book"
        assert entry.planned_author_name == "Future Author"
        assert entry.planned_format == "physical"
        assert entry.position == 3.5
        assert entry.notes == "Buy later"


def test_add_planned_series_entry_validates_title_format_and_position() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Planned Validation")

    response = client.post(
        f"/series/{series.id}/planned/add",
        data={"planned_title": " ", "planned_format": "scroll", "position": "soon"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?error=Planned+title+is+required."
    with session_factory() as db:
        assert db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).all() == []


def test_update_planned_series_entry_changes_metadata_and_order() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Planned Edit")
    add_series_entry(
        session_factory,
        series.id,
        position=5,
        planned_title="Original Planned",
        planned_author_name="Original Author",
        planned_format="ebook",
    )
    with session_factory() as db:
        entry = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).one()

    response = client.post(
        f"/series/{series.id}/planned/{entry.id}/edit",
        data={
            "planned_title": "Updated Planned",
            "planned_author_name": "Updated Author",
            "planned_format": "audiobook",
            "position": "1.25",
            "notes": "Updated note",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?message=Updated+planned+book%3A+Updated+Planned"
    with session_factory() as db:
        updated = db.get(SeriesBook, entry.id)
        assert updated is not None
        assert updated.book_id is None
        assert updated.planned_title == "Updated Planned"
        assert updated.planned_author_name == "Updated Author"
        assert updated.planned_format == "audiobook"
        assert updated.position == 1.25
        assert updated.notes == "Updated note"


def test_remove_planned_series_entry_deletes_only_planned_entry() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Planned Remove")
    book = add_book(session_factory, title="Owned Book", author="Author")
    add_series_entry(session_factory, series.id, position=1, book_id=book.id)
    add_series_entry(session_factory, series.id, position=2, planned_title="Remove Me")
    with session_factory() as db:
        planned = db.scalars(
            select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.book_id.is_(None))
        ).one()

    response = client.post(
        f"/series/{series.id}/planned/{planned.id}/remove",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?message=Removed+planned+book+from+this+series."
    with session_factory() as db:
        entries = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).all()
        assert len(entries) == 1
        assert entries[0].book_id == book.id


def test_convert_planned_entry_to_existing_book_assignment() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Planned Convert")
    book = add_book(session_factory, title="Now Owned", author="Author", metadata_source="manual")
    add_series_entry(
        session_factory,
        series.id,
        position=4,
        planned_title="Planned Placeholder",
        planned_author_name="Placeholder Author",
        planned_format="ebook",
    )
    with session_factory() as db:
        planned = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).one()

    response = client.post(
        f"/series/{series.id}/planned/{planned.id}/convert",
        data={"book_id": str(book.id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?message=Converted+planned+entry+to+Now+Owned."
    with session_factory() as db:
        converted = db.get(SeriesBook, planned.id)
        assert converted is not None
        assert converted.book_id == book.id
        assert converted.position == 4
        assert converted.planned_title is None
        assert converted.planned_author_name is None
        assert converted.planned_format is None
        assert db.get(Book, book.id) is not None


def test_convert_planned_entry_rejects_duplicate_existing_book() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Duplicate Convert")
    book = add_book(session_factory, title="Already Assigned", author="Author")
    add_series_entry(session_factory, series.id, position=1, book_id=book.id)
    add_series_entry(session_factory, series.id, position=2, planned_title="Duplicate Placeholder")
    with session_factory() as db:
        planned = db.scalars(
            select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.book_id.is_(None))
        ).one()

    response = client.post(
        f"/series/{series.id}/planned/{planned.id}/convert",
        data={"book_id": str(book.id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/series/{series.id}?error=Already+Assigned+is+already+in+this+series."
    with session_factory() as db:
        unchanged = db.get(SeriesBook, planned.id)
        assert unchanged is not None
        assert unchanged.book_id is None
        assert unchanged.planned_title == "Duplicate Placeholder"


def test_series_detail_documents_ordering_semantics() -> None:
    client, session_factory = make_series_client(admin_password=None)
    series = add_series(session_factory, name="Ordering Help")

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "Use whole numbers for main books" in response.text
    assert "decimals for novellas" in response.text
    assert "negative numbers for prequels" in response.text
    assert "Unknown-position entries appear after numbered entries" in response.text


def test_series_entries_sort_by_prequel_decimal_whole_then_unknown_title() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Ordering Semantics")
    main = add_book(session_factory, title="Main Book", author="Author")
    sequel = add_book(session_factory, title="Sequel Book", author="Author")
    add_series_entry(session_factory, series.id, position=1, book_id=main.id)
    add_series_entry(session_factory, series.id, position=2, book_id=sequel.id)
    add_series_entry(session_factory, series.id, position=-1, planned_title="Prequel Book")
    add_series_entry(session_factory, series.id, position=1.5, planned_title="Novella Book")
    add_series_entry(session_factory, series.id, position=None, planned_title="Zulu Unknown")
    add_series_entry(session_factory, series.id, position=None, planned_title="Alpha Unknown")

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    table_html = response.text[response.text.find("Books In Series") :]
    assert table_html.find("Prequel Book") < table_html.find("Main Book")
    assert table_html.find("Main Book") < table_html.find("Novella Book")
    assert table_html.find("Novella Book") < table_html.find("Sequel Book")
    assert table_html.find("Sequel Book") < table_html.find("Alpha Unknown")
    assert table_html.find("Alpha Unknown") < table_html.find("Zulu Unknown")


def test_clearing_existing_book_position_moves_entry_to_unknown_group() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Clear Owned Position")
    first = add_book(session_factory, title="First Numbered", author="Author")
    second = add_book(session_factory, title="Second Cleared", author="Author")
    add_series_entry(session_factory, series.id, position=1, book_id=first.id)
    add_series_entry(session_factory, series.id, position=2, book_id=second.id)
    with session_factory() as db:
        second_entry = db.scalars(
            select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.book_id == second.id)
        ).one()

    response = client.post(
        f"/series/{series.id}/entries/{second_entry.id}/position",
        data={"position": ""},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        updated = db.get(SeriesBook, second_entry.id)
        assert updated is not None
        assert updated.position is None
    follow_response = client.get(response.headers["location"])
    table_html = follow_response.text[follow_response.text.find("Books In Series") :]
    assert table_html.find("First Numbered") < table_html.find("Second Cleared")
    assert "Unknown" in table_html


def test_clearing_planned_position_moves_entry_to_unknown_group() -> None:
    client, session_factory = make_series_client()
    login_as_admin(client)
    series = add_series(session_factory, name="Clear Planned Position")
    add_series_entry(session_factory, series.id, position=1, planned_title="Numbered Planned")
    add_series_entry(session_factory, series.id, position=2, planned_title="Cleared Planned")
    with session_factory() as db:
        cleared = db.scalars(
            select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.planned_title == "Cleared Planned")
        ).one()

    response = client.post(
        f"/series/{series.id}/planned/{cleared.id}/edit",
        data={
            "planned_title": "Cleared Planned",
            "planned_author_name": "",
            "planned_format": "ebook",
            "position": "",
            "notes": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        updated = db.get(SeriesBook, cleared.id)
        assert updated is not None
        assert updated.position is None
    follow_response = client.get(response.headers["location"])
    table_html = follow_response.text[follow_response.text.find("Books In Series") :]
    assert table_html.find("Numbered Planned") < table_html.find("Cleared Planned")


def test_series_detail_counts_planned_entries_as_remaining() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Remaining Planned", status="active")
    completed = add_book(session_factory, title="Finished Book", author="Author", status="completed")
    add_series_entry(session_factory, series.id, position=1, book_id=completed.id)
    add_series_entry(session_factory, series.id, position=2, planned_title="Future Planned")

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "1 / 2" in response.text
    assert "Remaining" in response.text
    assert "1 tracked entries remain unread or planned." in response.text
    assert "Future Planned" in response.text
    assert "Next unread" in response.text


def test_series_detail_marks_all_complete_without_auto_completing_series_status() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Manual Status", status="active")
    first = add_book(session_factory, title="Complete One", author="Author", status="completed")
    second = add_book(session_factory, title="Complete Two", author="Author", status="started")
    add_series_entry(session_factory, series.id, position=1, book_id=first.id)
    add_series_entry(session_factory, series.id, position=2, book_id=second.id)
    with session_factory() as db:
        db.add(
            BookProgress(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=second.id,
                source="manual",
                progress_percent=100,
            )
        )
        db.commit()

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "2 / 2" in response.text
    assert "All tracked entries are complete or read. Series status remains manual." in response.text
    assert "Active" in response.text
    with session_factory() as db:
        unchanged = db.get(Series, series.id)
        assert unchanged is not None
        assert unchanged.status == "active"


def test_series_detail_completed_status_warns_when_entries_remain() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="Completed With Remainder", status="completed")
    read_book = add_book(session_factory, title="Read Book", author="Author", status="completed")
    unread_book = add_book(session_factory, title="Unread Book", author="Author", status="want_to_read")
    add_series_entry(session_factory, series.id, position=1, book_id=read_book.id)
    add_series_entry(session_factory, series.id, position=2, book_id=unread_book.id)
    add_series_entry(session_factory, series.id, position=3, planned_title="Planned Remainder")

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "1 / 3" in response.text
    assert "Series is marked Completed, but 2 tracked entries remain unread or planned." in response.text
    assert "Unread Book" in response.text


def test_series_detail_paused_and_abandoned_keep_next_unread_visible() -> None:
    client, session_factory = make_series_client()
    paused = add_series(session_factory, name="Paused Series", status="paused")
    abandoned = add_series(session_factory, name="Abandoned Series", status="abandoned")
    paused_book = add_book(session_factory, title="Paused Next", author="Author", status="want_to_read")
    abandoned_book = add_book(session_factory, title="Abandoned Next", author="Author", status="want_to_read")
    add_series_entry(session_factory, paused.id, position=1, book_id=paused_book.id)
    add_series_entry(session_factory, abandoned.id, position=1, book_id=abandoned_book.id)

    paused_response = client.get(f"/series/{paused.id}")
    abandoned_response = client.get(f"/series/{abandoned.id}")

    assert paused_response.status_code == 200
    assert "Series is paused. Next unread remains Paused Next." in paused_response.text
    assert "Paused Next" in paused_response.text
    assert abandoned_response.status_code == 200
    assert "Series is abandoned. Next unread remains Abandoned Next if you resume." in abandoned_response.text
    assert "Abandoned Next" in abandoned_response.text


def test_series_detail_empty_series_progress_note() -> None:
    client, session_factory = make_series_client()
    series = add_series(session_factory, name="No Progress Yet", status="unknown")

    response = client.get(f"/series/{series.id}")

    assert response.status_code == 200
    assert "0 / 0" in response.text
    assert "No books or planned entries are tracked yet." in response.text
