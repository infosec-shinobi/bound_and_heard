from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.write_protection import require_write_access
from app.main import create_app


def make_client(admin_password: str | None = "secret") -> TestClient:
    app = create_app(
        Settings(
            admin_password=admin_password,
            session_secret="test-session-secret",
            database_url="sqlite:///:memory:",
        )
    )

    @app.post("/mutate")
    async def mutate(_: None = Depends(require_write_access)) -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_read_only_route_works_without_admin_password() -> None:
    client = make_client(admin_password=None)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_write_action_blocked_when_admin_password_missing() -> None:
    client = make_client(admin_password=None)

    response = client.post("/mutate")

    assert response.status_code == 403
    assert "BOUND_AND_HEARD_ADMIN_PASSWORD" in response.json()["detail"]


def test_write_action_requires_admin_login() -> None:
    client = make_client()

    response = client.post("/mutate")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin login is required for write actions."


def test_admin_login_enables_write_actions() -> None:
    client = make_client()

    login_response = client.post("/admin/login", data={"password": "secret"}, follow_redirects=False)
    assert login_response.status_code == 303

    response = client.post("/mutate")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_invalid_admin_password_is_rejected() -> None:
    client = make_client()

    login_response = client.post("/admin/login", data={"password": "wrong"})
    assert login_response.status_code == 401

    response = client.post("/mutate")
    assert response.status_code == 403


def test_logout_disables_write_actions_for_session() -> None:
    client = make_client()
    client.post("/admin/login", data={"password": "secret"})

    logout_response = client.post("/admin/logout", follow_redirects=False)
    assert logout_response.status_code == 303

    response = client.post("/mutate")
    assert response.status_code == 403



def test_login_page_shows_disabled_message_when_password_missing() -> None:
    client = make_client(admin_password=None)

    response = client.get("/admin/login")

    assert response.status_code == 200
    assert "Write actions are disabled" in response.text


def test_admin_index_redirects_to_login() -> None:
    client = make_client()

    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_dashboard_is_read_only_accessible_without_admin_password() -> None:
    client = make_client(admin_password=None)

    response = client.get("/")

    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "Read-only mode" in response.text
    assert "Set BOUND_AND_HEARD_ADMIN_PASSWORD" in response.text


def test_dashboard_shows_admin_login_required_when_writes_configured() -> None:
    client = make_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "Admin login required" in response.text
    assert "Admin login is required for write actions." in response.text


def test_dashboard_shows_writes_unlocked_after_login() -> None:
    client = make_client()
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/")

    assert response.status_code == 200
    assert "Writes unlocked" in response.text
    assert "Write actions are enabled for this admin session." in response.text
