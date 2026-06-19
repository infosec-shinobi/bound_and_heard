from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import User


def make_settings_client(admin_password: str | None = "secret") -> tuple[TestClient, sessionmaker[Session]]:
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


def test_settings_page_requires_admin_login() -> None:
    client, _ = make_settings_client()

    response = client.get("/settings")

    assert response.status_code == 403


def test_settings_page_shows_current_display_name_after_login() -> None:
    client, _ = make_settings_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Settings" in response.text
    assert "Local User" in response.text


def test_update_settings_changes_display_name_and_redirects() -> None:
    client, session_factory = make_settings_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/settings",
        data={"display_name": "Reader Name", "theme": "dark"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings"

    with session_factory() as db:
        user = db.get(User, DEFAULT_LOCAL_USER_ID)
        assert user is not None
        assert user.display_name == "Reader Name"


def test_update_settings_validates_display_name() -> None:
    client, session_factory = make_settings_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post("/settings", data={"display_name": " ", "theme": "light"})

    assert response.status_code == 400
    assert "Display name is required." in response.text

    with session_factory() as db:
        user = db.get(User, DEFAULT_LOCAL_USER_ID)
        assert user is not None
        assert user.display_name == "Local User"


def test_theme_cookie_is_applied_in_base_template() -> None:
    client, _ = make_settings_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/settings",
        data={"display_name": "Local User", "theme": "light"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.cookies.get("theme") == "light"

    themed_response = client.get("/")
    assert themed_response.status_code == 200
    assert '<html lang="en" data-bs-theme="light">' in themed_response.text
