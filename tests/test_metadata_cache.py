from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import MetadataCacheEntry
from app.services.metadata_cache import (
    get_or_fetch_metadata_response,
    metadata_response_checksum,
    store_metadata_lookup_response,
)
from app.services.metadata_providers import MetadataLookupResponse


class FakeProvider:
    name = "fake_provider"

    def lookup_isbn(self, isbn: str) -> MetadataLookupResponse:
        raise NotImplementedError

    def lookup_title_author(self, title: str, author: str | None = None) -> MetadataLookupResponse:
        raise NotImplementedError


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def make_response(status: str = "succeeded", raw_response: object | None = None, error_message: str | None = None) -> MetadataLookupResponse:
    return MetadataLookupResponse(
        provider="fake_provider",
        lookup_type="isbn",
        normalized_query="9781234567890",
        status=status,
        raw_response=raw_response if raw_response is not None else {"items": [{"id": "one"}]},
        http_status=200,
        error_message=error_message,
    )


def test_checksum_is_stable_for_equivalent_payloads() -> None:
    left = metadata_response_checksum({"b": 2, "a": 1}, status="succeeded")
    right = metadata_response_checksum({"a": 1, "b": 2}, status="succeeded")

    assert left == right


def test_store_metadata_lookup_response_creates_cache_entry() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        cache_entry = store_metadata_lookup_response(db, make_response())

        assert cache_entry.id is not None
        assert cache_entry.provider == "fake_provider"
        assert cache_entry.lookup_type == "isbn"
        assert cache_entry.normalized_query == "9781234567890"
        assert cache_entry.status == "succeeded"
        assert cache_entry.http_status == 200
        assert cache_entry.raw_response == {"items": [{"id": "one"}]}


def test_store_metadata_lookup_response_reuses_same_checksum_entry() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        first = store_metadata_lookup_response(db, make_response())
        second = store_metadata_lookup_response(db, make_response())

        entries = db.scalars(select(MetadataCacheEntry)).all()
        assert first.id == second.id
        assert len(entries) == 1


def test_get_or_fetch_metadata_response_uses_cache_hit_without_provider_call() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        store_metadata_lookup_response(db, make_response(raw_response={"items": [{"id": "cached"}]}))
        calls = 0

        def lookup() -> MetadataLookupResponse:
            nonlocal calls
            calls += 1
            return make_response(raw_response={"items": [{"id": "fresh"}]})

        result = get_or_fetch_metadata_response(
            db,
            provider=FakeProvider(),
            lookup_type="isbn",
            normalized_query="9781234567890",
            lookup=lookup,
        )

        assert result.from_cache is True
        assert result.response.raw_response == {"items": [{"id": "cached"}]}
        assert calls == 0


def test_get_or_fetch_metadata_response_force_refresh_calls_provider() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        store_metadata_lookup_response(db, make_response(raw_response={"items": [{"id": "cached"}]}))

        def lookup() -> MetadataLookupResponse:
            return make_response(raw_response={"items": [{"id": "fresh"}]})

        result = get_or_fetch_metadata_response(
            db,
            provider=FakeProvider(),
            lookup_type="isbn",
            normalized_query="9781234567890",
            lookup=lookup,
            force_refresh=True,
        )

        assert result.from_cache is False
        assert result.response.raw_response == {"items": [{"id": "fresh"}]}
        assert db.scalar(select(MetadataCacheEntry).where(MetadataCacheEntry.raw_response == {"items": [{"id": "fresh"}]})) is not None


def test_empty_and_failed_responses_are_cacheable_to_avoid_tight_retries() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        no_results = store_metadata_lookup_response(db, make_response(status="no_results", raw_response={"items": []}))
        failed = store_metadata_lookup_response(db, make_response(status="failed", raw_response=None, error_message="timed out"))

        assert no_results.status == "no_results"
        assert failed.status == "failed"

        calls = 0

        def lookup() -> MetadataLookupResponse:
            nonlocal calls
            calls += 1
            return make_response()

        cached = get_or_fetch_metadata_response(
            db,
            provider=FakeProvider(),
            lookup_type="isbn",
            normalized_query="9781234567890",
            lookup=lookup,
        )

        assert cached.from_cache is True
        assert cached.response.status in {"no_results", "failed"}
        assert calls == 0
