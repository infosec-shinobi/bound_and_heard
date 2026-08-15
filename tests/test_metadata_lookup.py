from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, User
from app.services.metadata_lookup import lookup_book_metadata
from app.services.metadata_providers import MetadataLookupResponse, MetadataResult


class FakeProvider:
    def __init__(self, name: str, isbn_results=(), title_results=()):
        self.name = name
        self.isbn_results = tuple(isbn_results)
        self.title_results = tuple(title_results)
        self.isbn_calls = 0
        self.title_calls = 0

    def lookup_isbn(self, isbn: str) -> MetadataLookupResponse:
        self.isbn_calls += 1
        return MetadataLookupResponse(
            provider=self.name,
            lookup_type="isbn",
            normalized_query=isbn,
            status="succeeded" if self.isbn_results else "no_results",
            results=self.isbn_results,
            raw_response={"results": [result.title for result in self.isbn_results]},
            http_status=200,
        )

    def lookup_title_author(self, title: str, author: str | None = None) -> MetadataLookupResponse:
        self.title_calls += 1
        normalized_query = f"{title.casefold()}|{(author or '').casefold()}" if author else title.casefold()
        return MetadataLookupResponse(
            provider=self.name,
            lookup_type="title_author",
            normalized_query=normalized_query,
            status="succeeded" if self.title_results else "no_results",
            results=self.title_results,
            raw_response={"results": [result.title for result in self.title_results]},
            http_status=200,
        )

    def parse_cached_response(
        self,
        *,
        lookup_type: str,
        normalized_query: str,
        status: str,
        raw_response,
        http_status: int | None = None,
        error_message: str | None = None,
    ) -> MetadataLookupResponse:
        results = self.isbn_results if lookup_type == "isbn" else self.title_results
        return MetadataLookupResponse(
            provider=self.name,
            lookup_type=lookup_type,
            normalized_query=normalized_query,
            status=status,
            results=results if status == "succeeded" else (),
            raw_response=raw_response,
            http_status=http_status,
            error_message=error_message,
        )


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def add_book(db: Session, **kwargs) -> Book:
    db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=kwargs.pop("title", "Example Book"),
        primary_author_name=kwargs.pop("primary_author_name", "Jane Doe"),
        isbn13=kwargs.pop("isbn13", None),
        format="ebook",
        status="unknown",
        **kwargs,
    )
    db.add(book)
    db.flush()
    return book


def result(title: str = "Example Book", author: str = "Jane Doe", confidence: float = 0.7, isbn13: str | None = None) -> MetadataResult:
    return MetadataResult(
        provider="fake",
        title=title,
        authors=(author,),
        isbn13=isbn13,
        confidence=confidence,
    )


def test_lookup_prefers_isbn_and_does_not_fall_back_when_isbn_finds_candidate() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db, isbn13="9781234567890")
        provider = FakeProvider("fake", isbn_results=(result(confidence=0.95, isbn13="9781234567890"),), title_results=(result(title="Other"),))

        outcome = lookup_book_metadata(db, book=book, providers=[provider])

        assert outcome.status == "matched"
        assert outcome.best_candidate is not None
        assert outcome.best_candidate.response.lookup_type == "isbn"
        assert provider.isbn_calls == 1
        assert provider.title_calls == 0


def test_lookup_falls_back_to_title_author_when_isbn_has_no_results() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db, isbn13="9781234567890")
        provider = FakeProvider("fake", title_results=(result(confidence=0.82),))

        outcome = lookup_book_metadata(db, book=book, providers=[provider])

        assert outcome.status == "matched"
        assert outcome.best_candidate is not None
        assert outcome.best_candidate.response.lookup_type == "title_author"
        assert provider.isbn_calls == 1
        assert provider.title_calls == 1


def test_lookup_uses_cache_for_repeated_identical_lookup() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db, isbn13="9781234567890")
        provider = FakeProvider("fake", isbn_results=(result(confidence=0.95, isbn13="9781234567890"),))

        first = lookup_book_metadata(db, book=book, providers=[provider])
        second = lookup_book_metadata(db, book=book, providers=[provider])

        assert first.best_candidate is not None
        assert first.best_candidate.from_cache is False
        assert second.best_candidate is not None
        assert second.best_candidate.from_cache is True
        assert provider.isbn_calls == 1


def test_lookup_marks_low_confidence_title_author_result_without_silent_match() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db, isbn13=None)
        provider = FakeProvider("fake", title_results=(result(title="Different Book", author="Other", confidence=0.7),))

        outcome = lookup_book_metadata(db, book=book, providers=[provider])

        assert outcome.status == "low_confidence"
        assert outcome.best_candidate is not None
        assert outcome.best_candidate.score < 0.85


def test_lookup_marks_close_top_candidates_as_ambiguous() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db, isbn13=None)
        provider = FakeProvider(
            "fake",
            title_results=(
                result(title="Example Book", author="Jane Doe", confidence=0.86),
                result(title="Example Book", author="Jane Doe", confidence=0.85),
            ),
        )

        outcome = lookup_book_metadata(db, book=book, providers=[provider])

        assert outcome.status == "ambiguous"
        assert len(outcome.candidates) == 2


def test_lookup_returns_no_candidates_when_all_providers_are_empty() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        book = add_book(db, isbn13=None)
        provider = FakeProvider("fake")

        outcome = lookup_book_metadata(db, book=book, providers=[provider])

        assert outcome.status == "no_candidates"
        assert outcome.candidates == ()
