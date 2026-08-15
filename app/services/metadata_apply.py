from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Book, MetadataEnrichmentRun
from app.services.metadata_providers import MetadataResult


@dataclass(frozen=True)
class MetadataApplyResult:
    updated: bool
    fields_applied: dict[str, dict[str, Any]]
    run: MetadataEnrichmentRun


def apply_metadata_result_to_empty_fields(
    db: Session,
    *,
    book: Book,
    result: MetadataResult,
    cache_entry_id: int | None = None,
    lookup_type: str | None = None,
    normalized_query: str | None = None,
) -> MetadataApplyResult:
    fields_applied: dict[str, dict[str, Any]] = {}
    field_values = {
        "subtitle": result.subtitle,
        "publisher": result.publisher,
        "published_on": result.published_on,
        "publication_year": result.publication_year,
        "isbn10": result.isbn10,
        "isbn13": result.isbn13,
        "page_count": result.page_count,
        "cover_url": result.cover_url,
    }
    for field_name, value in field_values.items():
        if value is not None and _is_empty(getattr(book, field_name)):
            setattr(book, field_name, value)
            fields_applied[field_name] = {"source": result.provider, "value": _json_safe_value(value)}

    if fields_applied and _is_empty(book.metadata_source):
        book.metadata_source = result.provider
        fields_applied["metadata_source"] = {"source": result.provider, "value": result.provider}

    now = datetime.now(timezone.utc)
    run = MetadataEnrichmentRun(
        user_id=book.user_id,
        book_id=book.id,
        provider=result.provider,
        lookup_type=lookup_type,
        normalized_query=normalized_query,
        status="completed" if fields_applied else "skipped",
        cache_entry_id=cache_entry_id,
        fields_applied=fields_applied,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    return MetadataApplyResult(bool(fields_applied), fields_applied, run)


def _is_empty(value: object) -> bool:
    return value is None or value == ""


def _json_safe_value(value: object) -> object:
    return value.isoformat() if hasattr(value, "isoformat") else value
