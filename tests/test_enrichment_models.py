import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, MetadataCacheEntry, MetadataEnrichmentRun, User


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


def test_enrichment_schema_contains_expected_fields_indexes_and_constraints() -> None:
    session_factory = make_session_factory()
    inspector = inspect(session_factory.kw["bind"])

    assert "metadata_cache_entries" in inspector.get_table_names()
    assert "metadata_enrichment_runs" in inspector.get_table_names()

    book_columns = {column["name"] for column in inspector.get_columns("books")}
    assert {"published_on", "publication_year"}.issubset(book_columns)

    cache_columns = {column["name"] for column in inspector.get_columns("metadata_cache_entries")}
    assert {
        "id",
        "provider",
        "lookup_type",
        "normalized_query",
        "response_checksum",
        "status",
        "http_status",
        "error_message",
        "raw_response",
        "fetched_at",
        "created_at",
        "updated_at",
    }.issubset(cache_columns)

    run_columns = {column["name"] for column in inspector.get_columns("metadata_enrichment_runs")}
    assert {
        "id",
        "user_id",
        "book_id",
        "provider",
        "lookup_type",
        "normalized_query",
        "status",
        "cache_entry_id",
        "fields_applied",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    }.issubset(run_columns)

    cache_indexes = {index["name"] for index in inspector.get_indexes("metadata_cache_entries")}
    assert {
        "ix_metadata_cache_entries_provider",
        "ix_metadata_cache_entries_lookup_type",
        "ix_metadata_cache_entries_normalized_query",
        "ix_metadata_cache_entries_status",
        "ix_metadata_cache_entries_fetched_at",
    }.issubset(cache_indexes)

    run_indexes = {index["name"] for index in inspector.get_indexes("metadata_enrichment_runs")}
    assert {
        "ix_metadata_enrichment_runs_user_id",
        "ix_metadata_enrichment_runs_book_id",
        "ix_metadata_enrichment_runs_status",
        "ix_metadata_enrichment_runs_provider",
        "ix_metadata_enrichment_runs_lookup_type",
        "ix_metadata_enrichment_runs_created_at",
    }.issubset(run_indexes)

    unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("metadata_cache_entries")}
    assert "uq_metadata_cache_provider_lookup_query_checksum" in unique_constraints


def test_metadata_cache_and_enrichment_run_relationships() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        add_user(db)
        book = Book(user_id=DEFAULT_LOCAL_USER_ID, title="Enriched Book", format="ebook", status="unknown")
        cache_entry = MetadataCacheEntry(
            provider="open_library",
            lookup_type="isbn",
            normalized_query="9781234567890",
            response_checksum="abc123",
            status="succeeded",
            http_status=200,
            raw_response={"title": "Enriched Book"},
        )
        db.add_all([book, cache_entry])
        db.flush()
        run = MetadataEnrichmentRun(
            user_id=DEFAULT_LOCAL_USER_ID,
            book_id=book.id,
            provider="open_library",
            lookup_type="isbn",
            normalized_query="9781234567890",
            status="completed",
            cache_entry_id=cache_entry.id,
            fields_applied={"page_count": 320},
        )
        db.add(run)
        db.commit()

        db.refresh(book)
        assert book.metadata_enrichment_runs[0].cache_entry.raw_response == {"title": "Enriched Book"}
        assert book.metadata_enrichment_runs[0].fields_applied == {"page_count": 320}


def test_metadata_cache_unique_constraint_allows_distinct_checksums_only() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        first = MetadataCacheEntry(
            provider="google_books",
            lookup_type="title_author",
            normalized_query="sample|author",
            response_checksum="same",
            status="succeeded",
            raw_response={"items": []},
        )
        db.add(first)
        db.flush()

        db.add(
            MetadataCacheEntry(
                provider="google_books",
                lookup_type="title_author",
                normalized_query="sample|author",
                response_checksum="same",
                status="succeeded",
                raw_response={"items": []},
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
