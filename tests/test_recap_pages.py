from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Book, Recap, ReadingEvent, User


def make_recaps_client(
    admin_password: str | None = "secret", *, recaps_dir: str = "data/recaps"
) -> tuple[TestClient, sessionmaker[Session]]:
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
            recaps_dir=recaps_dir,
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


def seed_completed_book(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as db:
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Generated Book",
            primary_author_name="Generated Author",
            format="ebook",
            page_count=300,
        )
        db.add(book)
        db.flush()
        db.add(
            ReadingEvent(
                user_id=DEFAULT_LOCAL_USER_ID,
                book_id=book.id,
                source="manual",
                source_event_id="generated-book-completed",
                event_type="completed",
                event_date=datetime(2026, 4, 10, tzinfo=timezone.utc),
                progress_percent=100,
            )
        )
        db.commit()


def recap_payload() -> dict[str, object]:
    return {
        "title": "Q2 2026 Recap",
        "summary": "Q2 2026 Recap: 3 completed book(s).",
        "completed_count": 3,
        "format_breakdown": {"audiobook": 1, "ebook": 2},
        "favorite_authors": [{"label": "Alice", "count": 2}],
        "favorite_genres": [{"label": "Sci Fi", "count": 2}],
        "favorite_series": [{"id": 1, "name": "Recap Saga", "completed_entries": 2}],
        "longest_book": {"id": 2, "title": "Long Audio", "author": "Bob", "metric": "seconds", "value": 7200},
        "most_active_month": {"year": 2026, "month": 5, "count": 2},
        "pages_read": 600,
        "audiobook_seconds": 7200,
        "lifetime_enjoyed_seconds": 14400,
        "repeats": {"rereads": 1, "relistens": 0, "repeat_completions": 0, "likely_relistens": 1},
        "series_progress": {
            "total_series": 1,
            "completed_series_entries": 2,
            "active_series_count": 1,
            "planned_entries": 1,
            "collection_range_entries": 1,
            "collection_covered_positions": 2,
        },
    }


def add_recap(
    session_factory: sessionmaker[Session], *, period_type: str = "quarter", year: int = 2026, quarter: int = 2
) -> Recap:
    title = "Q2 2026 Recap" if period_type == "quarter" else "2026 Recap"
    with session_factory() as db:
        recap = Recap(
            user_id=DEFAULT_LOCAL_USER_ID,
            period_type=period_type,
            year=year,
            quarter=quarter,
            generated_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
            title=title,
            summary=f"{title}: 3 completed book(s).",
            output_path=f"data/recaps/{period_type}/{year}.json",
            payload=recap_payload() | {"title": title, "summary": f"{title}: 3 completed book(s)."},
        )
        db.add(recap)
        db.commit()
        db.refresh(recap)
        return recap


def test_recaps_index_lists_generated_quarterly_and_yearly_recaps() -> None:
    client, session_factory = make_recaps_client()
    add_recap(session_factory)
    add_recap(session_factory, period_type="year", quarter=0)

    response = client.get("/recaps")

    assert response.status_code == 200
    assert "Recaps" in response.text
    assert "Q2 2026 Recap" in response.text
    assert "2026 Recap" in response.text
    assert 'href="/recaps/quarter/2026/2"' in response.text
    assert 'href="/recaps/year/2026"' in response.text


def test_recaps_index_shows_admin_generation_form_after_login(tmp_path: Path) -> None:
    client, _ = make_recaps_client(recaps_dir=str(tmp_path))

    read_only_response = client.get("/recaps")
    assert read_only_response.status_code == 200
    assert "Generate A Recap" in read_only_response.text
    assert 'action="/recaps/generate"' not in read_only_response.text

    client.post("/admin/login", data={"password": "secret"})
    response = client.get("/recaps")

    assert response.status_code == 200
    assert 'action="/recaps/generate"' in response.text
    assert 'name="period_type"' in response.text
    assert 'name="overwrite"' in response.text


def test_admin_can_generate_quarterly_recap_from_recaps_page(tmp_path: Path) -> None:
    client, session_factory = make_recaps_client(recaps_dir=str(tmp_path))
    seed_completed_book(session_factory)
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/recaps/generate",
        data={"period_type": "quarter", "year": "2026", "quarter": "2"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/recaps/quarter/2026/2")
    assert (tmp_path / "quarter" / "2026-q2.json").exists()
    with session_factory() as db:
        recap = db.query(Recap).filter_by(period_type="quarter", year=2026, quarter=2).one()
        assert recap.title == "Q2 2026 Recap"
        assert recap.payload["completed_count"] == 1


def test_generate_recap_requires_admin_login(tmp_path: Path) -> None:
    client, _ = make_recaps_client(recaps_dir=str(tmp_path))

    response = client.post(
        "/recaps/generate",
        data={"period_type": "year", "year": "2026", "quarter": "1"},
        headers={"accept": "text/html"},
    )

    assert response.status_code == 403
    assert "Admin login is required" in response.text
    assert not (tmp_path / "year" / "2026.json").exists()


def test_generate_recap_reports_existing_and_allows_overwrite(tmp_path: Path) -> None:
    client, session_factory = make_recaps_client(recaps_dir=str(tmp_path))
    seed_completed_book(session_factory)
    client.post("/admin/login", data={"password": "secret"})
    client.post("/recaps/generate", data={"period_type": "year", "year": "2026", "quarter": "1"})

    duplicate = client.post(
        "/recaps/generate",
        data={"period_type": "year", "year": "2026", "quarter": "1"},
        follow_redirects=True,
    )

    assert duplicate.status_code == 200
    assert "already exists" in duplicate.text
    assert "Check overwrite" in duplicate.text

    overwrite = client.post(
        "/recaps/generate",
        data={"period_type": "year", "year": "2026", "quarter": "1", "overwrite": "yes"},
        follow_redirects=True,
    )

    assert overwrite.status_code == 200
    assert "Generated 2026 Recap" in overwrite.text
    with session_factory() as db:
        assert db.query(Recap).filter_by(period_type="year", year=2026, quarter=0).count() == 1


def test_quarterly_recap_page_shows_recap_metrics() -> None:
    client, session_factory = make_recaps_client()
    add_recap(session_factory)

    response = client.get("/recaps/quarter/2026/2")

    assert response.status_code == 200
    assert "Quarterly recap" in response.text
    assert "Books Completed" in response.text
    assert "3" in response.text
    assert "Favorite Author" in response.text
    assert "Alice" in response.text
    assert "Favorite Genre" in response.text
    assert "Sci Fi" in response.text
    assert "Favorite Series" in response.text
    assert "Recap Saga" in response.text
    assert "Longest Book" in response.text
    assert "Long Audio" in response.text
    assert "Most Active Month" in response.text
    assert "2026-05" in response.text
    assert "Format Mix" in response.text
    assert "Audiobook" in response.text
    assert "Pages Read" in response.text
    assert "600" in response.text
    assert "Audiobook Hours" in response.text
    assert "2 hr" in response.text
    assert "Repeat Highlights" in response.text
    assert "estimated" in response.text
    assert "Series Progress" in response.text
    assert "Planned Entries" in response.text


def test_yearly_recap_page_is_read_only_without_admin_password_and_labels_missing_metrics() -> None:
    client, session_factory = make_recaps_client(admin_password=None)
    with session_factory() as db:
        db.add(
            Recap(
                user_id=DEFAULT_LOCAL_USER_ID,
                period_type="year",
                year=2026,
                quarter=0,
                generated_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
                title="2026 Recap",
                summary="2026 Recap: 0 completed book(s).",
                output_path="data/recaps/year/2026.json",
                payload={"completed_count": 0, "summary": "2026 Recap: 0 completed book(s)."},
            )
        )
        db.commit()

    response = client.get("/recaps/year/2026")

    assert response.status_code == 200
    assert "Yearly recap" in response.text
    assert "Read-only mode" in response.text
    assert "Not available" in response.text
    assert "method=\"post\"" not in response.text


def test_missing_recap_returns_404() -> None:
    client, _ = make_recaps_client()

    response = client.get("/recaps/year/2026")

    assert response.status_code == 404
