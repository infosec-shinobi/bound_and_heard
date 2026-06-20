import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Import, ImportFile, User


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_user(db: Session, user_id: int = DEFAULT_LOCAL_USER_ID) -> User:
    user = User(id=user_id, display_name=f"User {user_id}")
    db.add(user)
    db.commit()
    return user


def test_import_record_stores_source_file_status_summary_and_raw_path() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        import_record = Import(
            user_id=DEFAULT_LOCAL_USER_ID,
            source="libby",
            filename="timeline.json",
            checksum="abc123",
            row_count=42,
            status="completed",
            summary={"books_created": 5, "events_created": 37},
            raw_file_path="data/imports/libby/timeline.json",
        )
        db.add(import_record)
        db.commit()
        db.refresh(import_record)

    assert import_record.source == "libby"
    assert import_record.filename == "timeline.json"
    assert import_record.checksum == "abc123"
    assert import_record.row_count == 42
    assert import_record.status == "completed"
    assert import_record.summary == {"books_created": 5, "events_created": 37}
    assert import_record.raw_file_path == "data/imports/libby/timeline.json"
    assert import_record.imported_at is not None


def test_import_file_stores_raw_file_metadata() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        import_record = Import(
            user_id=DEFAULT_LOCAL_USER_ID,
            source="libby",
            filename="timeline.json",
            checksum="abc123",
            row_count=0,
            status="pending",
        )
        db.add(import_record)
        db.commit()

        import_file = ImportFile(
            import_id=import_record.id,
            file_path="data/imports/libby/timeline.json",
            file_size=2048,
            content_type="application/json",
        )
        db.add(import_file)
        db.commit()
        db.refresh(import_record)
        files = list(import_record.files)

    assert len(files) == 1
    assert files[0].file_path == "data/imports/libby/timeline.json"
    assert files[0].file_size == 2048
    assert files[0].content_type == "application/json"


def test_import_checksum_is_unique_per_user_and_source() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        db.add(
            Import(
                user_id=DEFAULT_LOCAL_USER_ID,
                source="libby",
                filename="first.json",
                checksum="duplicate-checksum",
                row_count=1,
                status="completed",
            )
        )
        db.commit()

        db.add(
            Import(
                user_id=DEFAULT_LOCAL_USER_ID,
                source="libby",
                filename="second.json",
                checksum="duplicate-checksum",
                row_count=1,
                status="pending",
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()


def test_import_checksum_can_repeat_for_different_source_or_user() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db, DEFAULT_LOCAL_USER_ID)
        add_user(db, 2)
        db.add_all(
            [
                Import(
                    user_id=DEFAULT_LOCAL_USER_ID,
                    source="libby",
                    filename="first.json",
                    checksum="same-checksum",
                    row_count=1,
                    status="completed",
                ),
                Import(
                    user_id=DEFAULT_LOCAL_USER_ID,
                    source="other",
                    filename="second.json",
                    checksum="same-checksum",
                    row_count=1,
                    status="completed",
                ),
                Import(
                    user_id=2,
                    source="libby",
                    filename="third.json",
                    checksum="same-checksum",
                    row_count=1,
                    status="completed",
                ),
            ]
        )
        db.commit()

        assert db.query(Import).count() == 3
