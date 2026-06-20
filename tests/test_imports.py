from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_imports_client(tmp_path: Path, admin_password: str | None = "secret") -> TestClient:
    app = create_app(
        Settings(
            admin_password=admin_password,
            session_secret="test-session-secret",
            database_url="sqlite:///:memory:",
            imports_dir=str(tmp_path),
        )
    )
    return TestClient(app)


def test_imports_page_requires_admin_login(tmp_path: Path) -> None:
    client = make_imports_client(tmp_path)

    response = client.get("/imports")

    assert response.status_code == 403


def test_imports_page_shows_upload_form_after_login(tmp_path: Path) -> None:
    client = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/imports")

    assert response.status_code == 200
    assert "Upload Libby JSON" in response.text
    assert 'enctype="multipart/form-data"' in response.text


def test_libby_upload_requires_write_access(tmp_path: Path) -> None:
    client = make_imports_client(tmp_path, admin_password=None)

    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", b'{"version": 1, "timeline": []}', "application/json")},
    )

    assert response.status_code == 403
    assert not (tmp_path / "libby").exists()


def test_libby_upload_rejects_non_json_extension(tmp_path: Path) -> None:
    client = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.txt", b'{"version": 1, "timeline": []}', "text/plain")},
    )

    assert response.status_code == 400
    assert "Libby export must be a .json file." in response.text
    assert not (tmp_path / "libby").exists()


def test_libby_upload_rejects_invalid_json(tmp_path: Path) -> None:
    client = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", b"not json", "application/json")},
    )

    assert response.status_code == 400
    assert "Uploaded file must contain valid JSON." in response.text
    assert not (tmp_path / "libby").exists()


def test_libby_upload_saves_valid_json_under_libby_imports_dir(tmp_path: Path) -> None:
    client = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    content = b'{"version": 1, "timeline": []}'
    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", content, "application/json")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/imports?saved_path=")

    saved_files = list((tmp_path / "libby").glob("*-timeline.json"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == content


def test_imports_nav_link_is_present(tmp_path: Path) -> None:
    client = make_imports_client(tmp_path, admin_password=None)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/imports"' in response.text
