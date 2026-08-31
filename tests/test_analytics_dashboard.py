from collections.abc import Generator
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Book, BookGenre, BookProgress, Genre, ReadingEvent, Series, SeriesBook, User


def make_analytics_client(admin_password: str | None = "secret") -> tuple[TestClient, sessionmaker[Session]]:
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
    db: Session,
    *,
    title: str,
    author: str,
    book_format: str,
    page_count: int | None = None,
    audio_seconds: int | None = None,
    status: str = "unknown",
    manual_progress_percent: float | None = None,
) -> Book:
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=title,
        primary_author_name=author,
        format=book_format,
        page_count=page_count,
        audio_seconds=audio_seconds,
        status=status,
        manual_progress_percent=manual_progress_percent,
    )
    db.add(book)
    db.flush()
    return book


def add_event(db: Session, book: Book, event_type: str, when: date, *, source: str = "manual") -> None:
    db.add(
        ReadingEvent(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            source=source,
            source_event_id=f"{book.id}:{event_type}:{when.isoformat()}",
            event_type=event_type,
            event_date=datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc),
            progress_percent=100 if event_type in {"completed", "manually_completed"} else None,
        )
    )
    db.flush()


def add_genre(db: Session, book: Book, name: str) -> None:
    genre = Genre(user_id=DEFAULT_LOCAL_USER_ID, name=name, normalized_name=name.casefold(), source="manual")
    db.add(genre)
    db.flush()
    db.add(BookGenre(user_id=DEFAULT_LOCAL_USER_ID, book_id=book.id, genre_id=genre.id, source="manual"))
    db.flush()


def add_series(db: Session, name: str, *, status: str = "active") -> Series:
    series = Series(user_id=DEFAULT_LOCAL_USER_ID, name=name, status=status, wants_to_continue="yes")
    db.add(series)
    db.flush()
    return series


def seed_dashboard_data(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as db:
        ebook = add_book(db, title="Quarter Ebook", author="Alice", book_format="ebook", page_count=300)
        audio = add_book(db, title="Quarter Audio", author="Bob", book_format="audiobook", audio_seconds=7200)
        prior_audio = add_book(db, title="Prior Audio", author="Bob", book_format="audiobook", audio_seconds=3600)
        started = add_book(
            db,
            title="Started Ebook",
            author="Cara",
            book_format="ebook",
            page_count=200,
            status="started",
            manual_progress_percent=25,
        )
        add_event(db, ebook, "completed", date(2026, 4, 10))
        add_event(db, audio, "completed", date(2025, 1, 1))
        add_event(db, audio, "completed", date(2026, 5, 1))
        add_event(db, prior_audio, "manually_completed", date(2026, 6, 1))
        add_event(db, audio, "borrowed", date(2025, 1, 1), source="libby")
        add_event(db, audio, "borrowed", date(2026, 5, 1), source="libby")
        db.add(BookProgress(user_id=audio.user_id, book_id=audio.id, source="scraped", enjoyed_seconds=14400))
        db.add(BookProgress(user_id=started.user_id, book_id=started.id, source="manual", progress_percent=25))
        add_genre(db, ebook, "Sci Fi")
        add_genre(db, audio, "Mystery")
        series = add_series(db, "Dashboard Saga")
        db.add(SeriesBook(series_id=series.id, book_id=ebook.id, position=1))
        db.add(SeriesBook(series_id=series.id, book_id=audio.id, position=2, position_end=3))
        db.add(SeriesBook(series_id=series.id, book_id=started.id, position=4))
        db.add(SeriesBook(series_id=series.id, position=5, planned_title="Dashboard Saga Five"))
        db.commit()


def test_analytics_dashboard_shows_period_metrics_and_nav_link() -> None:
    client, session_factory = make_analytics_client()
    seed_dashboard_data(session_factory)

    response = client.get("/analytics?period=quarter&year=2026&quarter=2")

    assert response.status_code == 200
    assert "Analytics" in response.text
    assert 'href="/analytics"' in response.text
    assert "2026-04" in response.text
    assert "2026-05" in response.text
    assert "2026-06" in response.text
    assert "Completed" in response.text
    assert "3" in response.text
    assert "Pages Read" in response.text
    assert "300" in response.text
    assert "Audiobook Time" in response.text
    assert "3 hr" in response.text
    assert "Lifetime Enjoyed" in response.text
    assert "5 hr" in response.text
    assert "Alice" in response.text
    assert "Bob" in response.text
    assert "Sci Fi" in response.text
    assert "Mystery" in response.text
    assert "Partial Progress" in response.text
    assert "25.0%" in response.text
    assert "Re-listens" in response.text
    assert "Likely Re-listens" in response.text
    assert "lower confidence" in response.text
    assert "Series Summary" in response.text
    assert "Series Activity" in response.text
    assert "Dashboard Saga" in response.text
    assert "Collection Ranges" in response.text
    assert "Dashboard Saga Five" not in response.text
    assert "Started Ebook" in response.text


def test_analytics_dashboard_is_available_read_only_without_admin_password() -> None:
    client, session_factory = make_analytics_client(admin_password=None)
    seed_dashboard_data(session_factory)

    response = client.get("/analytics?period=year&year=2026")

    assert response.status_code == 200
    assert "Read-only mode" in response.text
    assert "Analytics" in response.text
    assert "method=\"post\"" not in response.text
