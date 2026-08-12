from collections.abc import Generator
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import User
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
