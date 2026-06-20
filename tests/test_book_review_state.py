from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, User


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_user(db: Session) -> None:
    db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
    db.commit()


def test_book_review_state_defaults_to_unset() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Imported Book",
            format="audiobook",
            status="borrowed",
            metadata_source="libby",
        )
        db.add(book)
        db.commit()
        db.refresh(book)

    assert book.review_status is None
    assert book.reviewed_at is None
    assert book.review_note is None
    assert book.metadata_source == "libby"


def test_book_review_state_persists_reviewed_metadata() -> None:
    session_factory = make_session_factory()
    reviewed_at = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)

    with session_factory() as db:
        add_user(db)
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Reviewed Book",
            format="ebook",
            status="borrowed",
            review_status="reviewed",
            reviewed_at=reviewed_at,
            review_note="Cleaned up page count.",
        )
        db.add(book)
        db.commit()
        db.refresh(book)

    assert book.review_status == "reviewed"
    assert book.reviewed_at == reviewed_at.replace(tzinfo=None)
    assert book.review_note == "Cleaned up page count."


def test_book_review_state_supports_ignored_and_duplicate_candidate_filters() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        add_user(db)
        db.add_all(
            [
                Book(
                    user_id=DEFAULT_LOCAL_USER_ID,
                    title="Ignored Book",
                    format="ebook",
                    status="borrowed",
                    review_status="ignored",
                ),
                Book(
                    user_id=DEFAULT_LOCAL_USER_ID,
                    title="Duplicate Candidate",
                    format="ebook",
                    status="borrowed",
                    review_status="duplicate_candidate",
                ),
            ]
        )
        db.commit()

        ignored = db.query(Book).filter_by(review_status="ignored").one()
        duplicate = db.query(Book).filter_by(review_status="duplicate_candidate").one()

    assert ignored.title == "Ignored Book"
    assert duplicate.title == "Duplicate Candidate"
