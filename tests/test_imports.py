from collections.abc import Generator
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app
from app.models import Book, Import, ImportFile, ReadingEvent, User


def make_imports_client(
    tmp_path: Path,
    admin_password: str | None = "secret",
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
            imports_dir=str(tmp_path),
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


def test_imports_page_requires_admin_login(tmp_path: Path) -> None:
    client, _ = make_imports_client(tmp_path)

    response = client.get("/imports")

    assert response.status_code == 403


def test_imports_page_shows_upload_form_after_login(tmp_path: Path) -> None:
    client, _ = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/imports")

    assert response.status_code == 200
    assert "Upload Libby JSON" in response.text
    assert 'enctype="multipart/form-data"' in response.text


def test_libby_upload_requires_write_access(tmp_path: Path) -> None:
    client, _ = make_imports_client(tmp_path, admin_password=None)

    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", b'{"version": 1, "timeline": []}', "application/json")},
    )

    assert response.status_code == 403
    assert not (tmp_path / "libby").exists()


def test_libby_upload_rejects_non_json_extension(tmp_path: Path) -> None:
    client, _ = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.txt", b'{"version": 1, "timeline": []}', "text/plain")},
    )

    assert response.status_code == 400
    assert "Libby export must be a .json file." in response.text
    assert not (tmp_path / "libby").exists()


def test_libby_upload_rejects_invalid_json(tmp_path: Path) -> None:
    client, _ = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", b"not json", "application/json")},
    )

    assert response.status_code == 400
    assert "Uploaded file must contain valid JSON." in response.text
    assert not (tmp_path / "libby").exists()


def test_libby_upload_saves_valid_json_under_libby_imports_dir(tmp_path: Path) -> None:
    client, session_factory = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    content = b'{"version": 1, "timeline": []}'
    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", content, "application/json")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/imports/1?")
    assert "saved_path=" in response.headers["location"]

    saved_files = list((tmp_path / "libby").glob("*-timeline.json"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == content

    with session_factory() as db:
        import_record = db.query(Import).one()
        import_file = db.query(ImportFile).one()

    assert import_record.source == "libby"
    assert import_record.filename == "timeline.json"
    assert import_record.checksum == hashlib.sha256(content).hexdigest()
    assert import_record.row_count == 0
    assert import_record.status == "completed"
    assert import_record.summary == {
        "raw_json_preserved": True,
        "books_created": 0,
        "books_updated": 0,
        "events_created": 0,
        "duplicate_events_skipped": 0,
        "unsupported_events": 0,
        "book_ids": [],
    }
    assert import_record.raw_file_path == saved_files[0].as_posix()
    assert import_file.import_id == import_record.id
    assert import_file.file_path == saved_files[0].as_posix()
    assert import_file.file_size == len(content)
    assert import_file.content_type == "application/json"


def test_libby_upload_sets_row_count_from_timeline(tmp_path: Path) -> None:
    client, session_factory = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", b'{"version": 1, "timeline": [{}, {}]}', "application/json")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        import_record = db.query(Import).one()

    assert import_record.row_count == 2


def test_duplicate_libby_upload_skips_raw_save_and_import_record(tmp_path: Path) -> None:
    client, session_factory = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})
    content = b'{"version": 1, "timeline": []}'

    first_response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", content, "application/json")},
        follow_redirects=False,
    )
    second_response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", content, "application/json")},
        follow_redirects=False,
    )

    assert first_response.status_code == 303
    assert second_response.status_code == 303
    assert second_response.headers["location"].startswith("/imports/1?")
    assert "duplicate=1" in second_response.headers["location"]
    assert "checksum=" in second_response.headers["location"]
    assert len(list((tmp_path / "libby").glob("*-timeline.json"))) == 1

    with session_factory() as db:
        assert db.query(Import).count() == 1
        assert db.query(ImportFile).count() == 1


def test_imports_page_shows_duplicate_status(tmp_path: Path) -> None:
    client, session_factory = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    with session_factory() as db:
        import_record = Import(
            user_id=DEFAULT_LOCAL_USER_ID,
            source="libby",
            filename="timeline.json",
            checksum="abc123",
            row_count=1,
            status="uploaded",
        )
        db.add(import_record)
        db.commit()
        import_id = import_record.id

    response = client.get(f"/imports?duplicate_import_id={import_id}&checksum=abc123")

    assert response.status_code == 200
    assert "Duplicate Libby JSON skipped" in response.text
    assert f"import #{import_id}" in response.text
    assert "timeline.json" in response.text
    assert "Uploaded" in response.text


def test_import_detail_shows_summary_metadata_counts_and_book_links(tmp_path: Path) -> None:
    client, session_factory = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})
    content = b"""
    {
      "version": 1,
      "timeline": [
        {
          "cover": {"format": "audiobook"},
          "title": {"text": "Imported Book", "url": "https://share.libbyapp.com/title/1", "titleId": "1"},
          "author": "Import Author",
          "publisher": "Import Publisher",
          "isbn": "9781234567890",
          "timestamp": 1767903363000,
          "activity": "Borrowed",
          "library": {"key": "examplelibrary"}
        }
      ]
    }
    """

    upload_response = client.post(
        "/imports/libby",
        files={"file": ("timeline.json", content, "application/json")},
        follow_redirects=False,
    )

    assert upload_response.status_code == 303
    detail_response = client.get(upload_response.headers["location"])

    assert detail_response.status_code == 200
    assert "Import #1" in detail_response.text
    assert "timeline.json" in detail_response.text
    assert hashlib.sha256(content).hexdigest() in detail_response.text
    assert "Completed" in detail_response.text
    assert "Row Count" in detail_response.text
    assert "Books Created" in detail_response.text
    assert "Events Created" in detail_response.text
    assert "Duplicate Events Skipped" in detail_response.text
    assert "No duplicate file detected" in detail_response.text
    assert "Imported Book" in detail_response.text
    assert 'href="/books/1"' in detail_response.text

    with session_factory() as db:
        import_record = db.query(Import).one()
        assert import_record.row_count == 1
        assert import_record.summary["books_created"] == 1
        assert import_record.summary["events_created"] == 1
        assert db.query(Book).count() == 1
        assert db.query(ReadingEvent).count() == 1


def test_import_detail_shows_duplicate_file_status(tmp_path: Path) -> None:
    client, session_factory = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    with session_factory() as db:
        import_record = Import(
            user_id=DEFAULT_LOCAL_USER_ID,
            source="libby",
            filename="timeline.json",
            checksum="abc123",
            row_count=1,
            status="completed",
            summary={"books_created": 0, "events_created": 0},
        )
        db.add(import_record)
        db.commit()
        import_id = import_record.id

    response = client.get(f"/imports/{import_id}?duplicate=1")

    assert response.status_code == 200
    assert "Duplicate Libby JSON skipped" in response.text
    assert "Skipped duplicate upload" in response.text


def test_import_detail_returns_not_found_for_missing_import(tmp_path: Path) -> None:
    client, _ = make_imports_client(tmp_path)
    client.post("/admin/login", data={"password": "secret"})

    response = client.get("/imports/999")

    assert response.status_code == 404
    assert "Import not found" in response.text


def test_imports_nav_link_is_present(tmp_path: Path) -> None:
    client, _ = make_imports_client(tmp_path, admin_password=None)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/imports"' in response.text
