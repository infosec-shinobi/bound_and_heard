import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, BookGenre, Genre, User


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


def test_genre_schema_contains_expected_fields_indexes_and_constraints() -> None:
    session_factory = make_session_factory()
    inspector = inspect(session_factory.kw["bind"])

    assert "genres" in inspector.get_table_names()
    assert "book_genres" in inspector.get_table_names()

    genre_columns = {column["name"] for column in inspector.get_columns("genres")}
    assert {"id", "user_id", "name", "normalized_name", "source", "created_at", "updated_at"}.issubset(genre_columns)

    book_genre_columns = {column["name"] for column in inspector.get_columns("book_genres")}
    assert {"id", "user_id", "book_id", "genre_id", "source", "raw_label", "created_at", "updated_at"}.issubset(book_genre_columns)

    genre_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("genres")}
    assert "uq_genres_user_id_normalized_name" in genre_constraints

    book_genre_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("book_genres")}
    assert "uq_book_genres_book_id_genre_id" in book_genre_constraints


def test_genre_relationships_and_unique_constraints() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Genre Book", format="ebook", status="unknown")
        genre = Genre(user_id=DEFAULT_LOCAL_USER_ID, name="Science Fiction", normalized_name="science fiction", source="manual")
        db.add_all([book, genre])
        db.flush()
        db.add(BookGenre(user_id=DEFAULT_LOCAL_USER_ID, book_id=book.id, genre_id=genre.id, source="manual"))
        db.commit()

        db.refresh(book)
        assert book.genre_entries[0].genre.name == "Science Fiction"
        assert genre.books[0].book.title == "Genre Book"

        db.add(Genre(user_id=DEFAULT_LOCAL_USER_ID, name="science fiction", normalized_name="science fiction", source="google_books"))
        with pytest.raises(IntegrityError):
            db.flush()
