from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MetadataCacheEntry
from app.services.metadata_providers import MetadataLookupResponse, MetadataProvider


LookupFunction = Callable[[], MetadataLookupResponse]
CachedResponseParser = Callable[[MetadataCacheEntry], MetadataLookupResponse]


@dataclass(frozen=True)
class CachedMetadataLookup:
    response: MetadataLookupResponse
    cache_entry: MetadataCacheEntry
    from_cache: bool


def metadata_response_checksum(raw_response: object, *, status: str, error_message: str | None = None) -> str:
    payload = {
        "error_message": error_message,
        "raw_response": raw_response,
        "status": status,
    }
    serialized = dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


def find_cached_metadata_response(
    db: Session,
    *,
    provider: str,
    lookup_type: str,
    normalized_query: str,
) -> MetadataCacheEntry | None:
    return db.scalars(
        select(MetadataCacheEntry)
        .where(
            MetadataCacheEntry.provider == provider,
            MetadataCacheEntry.lookup_type == lookup_type,
            MetadataCacheEntry.normalized_query == normalized_query,
        )
        .order_by(MetadataCacheEntry.fetched_at.desc(), MetadataCacheEntry.id.desc())
    ).first()


def store_metadata_lookup_response(db: Session, response: MetadataLookupResponse) -> MetadataCacheEntry:
    checksum = metadata_response_checksum(
        response.raw_response,
        status=response.status,
        error_message=response.error_message,
    )
    existing = db.scalars(
        select(MetadataCacheEntry).where(
            MetadataCacheEntry.provider == response.provider,
            MetadataCacheEntry.lookup_type == response.lookup_type,
            MetadataCacheEntry.normalized_query == response.normalized_query,
            MetadataCacheEntry.response_checksum == checksum,
        )
    ).first()
    if existing is not None:
        existing.status = response.status
        existing.http_status = response.http_status
        existing.error_message = response.error_message
        existing.raw_response = response.raw_response
        existing.fetched_at = datetime.now(timezone.utc)
        db.flush()
        return existing

    cache_entry = MetadataCacheEntry(
        provider=response.provider,
        lookup_type=response.lookup_type,
        normalized_query=response.normalized_query,
        response_checksum=checksum,
        status=response.status,
        http_status=response.http_status,
        error_message=response.error_message,
        raw_response=response.raw_response,
    )
    db.add(cache_entry)
    db.flush()
    return cache_entry


def response_from_cache_entry(cache_entry: MetadataCacheEntry) -> MetadataLookupResponse:
    return MetadataLookupResponse(
        provider=cache_entry.provider,
        lookup_type=cache_entry.lookup_type,
        normalized_query=cache_entry.normalized_query,
        status=cache_entry.status,
        raw_response=cache_entry.raw_response,
        http_status=cache_entry.http_status,
        error_message=cache_entry.error_message,
    )


def get_or_fetch_metadata_response(
    db: Session,
    *,
    provider: MetadataProvider,
    lookup_type: str,
    normalized_query: str,
    lookup: LookupFunction,
    cached_response_parser: CachedResponseParser | None = None,
    force_refresh: bool = False,
) -> CachedMetadataLookup:
    if not force_refresh:
        cached = find_cached_metadata_response(
            db,
            provider=provider.name,
            lookup_type=lookup_type,
            normalized_query=normalized_query,
        )
        if cached is not None:
            response = cached_response_parser(cached) if cached_response_parser is not None else response_from_cache_entry(cached)
            return CachedMetadataLookup(response, cached, True)

    response = lookup()
    cache_entry = store_metadata_lookup_response(db, response)
    return CachedMetadataLookup(response, cache_entry, False)
