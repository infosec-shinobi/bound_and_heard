import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, LibbySeriesHint, Series, SeriesBook, User


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


def test_series_schema_contains_expected_fields_indexes_and_constraints() -> None:
    session_factory = make_session_factory()
    inspector = inspect(session_factory.kw["bind"])

    assert "series" in inspector.get_table_names()
    assert "series_books" in inspector.get_table_names()
    assert "libby_series_hints" in inspector.get_table_names()

    series_columns = {column["name"] for column in inspector.get_columns("series")}
    assert {
        "id",
        "user_id",
        "name",
        "description",
        "status",
        "wants_to_continue",
        "created_at",
        "updated_at",
    }.issubset(series_columns)

    series_book_columns = {column["name"] for column in inspector.get_columns("series_books")}
    assert {
        "id",
        "series_id",
        "book_id",
        "position",
        "planned_title",
        "planned_author_name",
        "planned_format",
        "notes",
        "created_at",
        "updated_at",
    }.issubset(series_book_columns)

    series_indexes = {index["name"] for index in inspector.get_indexes("series")}
    assert {"ix_series_user_id", "ix_series_status", "ix_series_wants_to_continue"}.issubset(series_indexes)

    series_book_indexes = {index["name"] for index in inspector.get_indexes("series_books")}
    assert {"ix_series_books_series_id", "ix_series_books_book_id", "ix_series_books_position"}.issubset(
        series_book_indexes
    )

    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("series_books")}
    assert "uq_series_books_series_id_book_id" in unique_constraints

    hint_columns = {column["name"] for column in inspector.get_columns("libby_series_hints")}
    assert {
        "id",
        "user_id",
        "book_id",
        "scrape_item_id",
        "libby_series_key",
        "libby_series_url",
        "raw_label",
        "series_name",
        "position",
        "status",
        "applied_at",
        "created_at",
        "updated_at",
    }.issubset(hint_columns)
    hint_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("libby_series_hints")}
    assert "uq_libby_series_hints_book_id_series_key" in hint_constraints


def test_series_defaults_and_relationships_support_owned_and_planned_entries() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Owned Entry", format="ebook", status="started")
        series = Series(user_id=DEFAULT_LOCAL_USER_ID, name="Schema Series")
        db.add_all([book, series])
        db.flush()
        db.add_all(
            [
                SeriesBook(series_id=series.id, book_id=book.id, position=1),
                SeriesBook(
                    series_id=series.id,
                    position=2.5,
                    planned_title="Planned Entry",
                    planned_author_name="Future Author",
                    planned_format="audiobook",
                    notes="Future note",
                ),
            ]
        )
        db.commit()

        db.refresh(series)
        db.refresh(book)

        assert series.status == "unknown"
        assert series.wants_to_continue == "unknown"
        assert len(series.books) == 2
        assert book.series_entries[0].series_id == series.id
        planned_entry = [entry for entry in series.books if entry.book_id is None][0]
        assert planned_entry.planned_title == "Planned Entry"
        assert planned_entry.planned_author_name == "Future Author"
        assert planned_entry.planned_format == "audiobook"
        assert planned_entry.notes == "Future note"


def test_series_book_unique_constraint_prevents_duplicate_owned_book_assignment() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Duplicate Owned", format="ebook", status="started")
        series = Series(user_id=DEFAULT_LOCAL_USER_ID, name="Duplicate Schema Series")
        db.add_all([book, series])
        db.flush()
        db.add(SeriesBook(series_id=series.id, book_id=book.id, position=1))
        db.flush()

        db.add(SeriesBook(series_id=series.id, book_id=book.id, position=2))
        with pytest.raises(IntegrityError):
            db.flush()


def test_libby_series_hint_relationship_defaults() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Hint Book", format="ebook", status="borrowed")
        db.add(book)
        db.flush()
        hint = LibbySeriesHint(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            libby_series_key="series-503231",
            libby_series_url="/shelf/series-503231/page-1",
            raw_label="#26 in Jack Reacher",
            series_name="Jack Reacher",
            position=26,
        )
        db.add(hint)
        db.commit()

        db.refresh(book)
        assert book.libby_series_hints[0].status == "pending"
        assert book.libby_series_hints[0].series_name == "Jack Reacher"
