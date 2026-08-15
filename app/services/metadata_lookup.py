from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Book, MetadataCacheEntry
from app.services.metadata_cache import get_or_fetch_metadata_response
from app.services.metadata_providers import (
    MetadataLookupResponse,
    MetadataProvider,
    MetadataResult,
    normalize_isbn_query,
    normalize_title_author_query,
)


@dataclass(frozen=True)
class MetadataCandidate:
    result: MetadataResult
    response: MetadataLookupResponse
    cache_entry: MetadataCacheEntry
    from_cache: bool
    score: float


@dataclass(frozen=True)
class MetadataLookupOutcome:
    status: str
    candidates: tuple[MetadataCandidate, ...] = ()
    attempted_lookups: tuple[MetadataLookupResponse, ...] = ()

    @property
    def best_candidate(self) -> MetadataCandidate | None:
        return self.candidates[0] if self.candidates else None


def lookup_book_metadata(
    db: Session,
    *,
    book: Book,
    providers: list[MetadataProvider],
    force_refresh: bool = False,
    minimum_auto_match_score: float = 0.85,
    ambiguity_score_gap: float = 0.05,
) -> MetadataLookupOutcome:
    attempted: list[MetadataLookupResponse] = []
    candidates: list[MetadataCandidate] = []
    isbn = normalize_isbn_query(book.isbn13 or book.isbn10 or "")
    if isbn:
        candidates.extend(
            _lookup_across_providers(
                db,
                book=book,
                providers=providers,
                lookup_type="isbn",
                normalized_query=isbn,
                attempted=attempted,
                force_refresh=force_refresh,
            )
        )
        if candidates:
            return _ranked_outcome(candidates, attempted, minimum_auto_match_score, ambiguity_score_gap)

    if book.title:
        normalized_query = normalize_title_author_query(book.title, book.primary_author_name)
        candidates.extend(
            _lookup_across_providers(
                db,
                book=book,
                providers=providers,
                lookup_type="title_author",
                normalized_query=normalized_query,
                attempted=attempted,
                force_refresh=force_refresh,
            )
        )
    if not candidates:
        return MetadataLookupOutcome("no_candidates", attempted_lookups=tuple(attempted))
    return _ranked_outcome(candidates, attempted, minimum_auto_match_score, ambiguity_score_gap)


def _lookup_across_providers(
    db: Session,
    *,
    book: Book,
    providers: list[MetadataProvider],
    lookup_type: str,
    normalized_query: str,
    attempted: list[MetadataLookupResponse],
    force_refresh: bool,
) -> list[MetadataCandidate]:
    candidates: list[MetadataCandidate] = []
    for provider in providers:
        if lookup_type == "isbn":
            lookup = lambda provider=provider: provider.lookup_isbn(normalized_query)
        else:
            lookup = lambda provider=provider: provider.lookup_title_author(book.title, book.primary_author_name)
        cached_lookup = get_or_fetch_metadata_response(
            db,
            provider=provider,
            lookup_type=lookup_type,
            normalized_query=normalized_query,
            lookup=lookup,
            cached_response_parser=lambda cache_entry, provider=provider: provider.parse_cached_response(
                lookup_type=cache_entry.lookup_type,
                normalized_query=cache_entry.normalized_query,
                status=cache_entry.status,
                raw_response=cache_entry.raw_response,
                http_status=cache_entry.http_status,
                error_message=cache_entry.error_message,
            ),
            force_refresh=force_refresh,
        )
        attempted.append(cached_lookup.response)
        for result in cached_lookup.response.results:
            candidates.append(
                MetadataCandidate(
                    result=result,
                    response=cached_lookup.response,
                    cache_entry=cached_lookup.cache_entry,
                    from_cache=cached_lookup.from_cache,
                    score=_score_result(book, result, lookup_type),
                )
            )
    return candidates


def _ranked_outcome(
    candidates: list[MetadataCandidate],
    attempted: list[MetadataLookupResponse],
    minimum_auto_match_score: float,
    ambiguity_score_gap: float,
) -> MetadataLookupOutcome:
    ranked = tuple(sorted(candidates, key=lambda candidate: candidate.score, reverse=True))
    if ranked[0].score < minimum_auto_match_score:
        return MetadataLookupOutcome("low_confidence", ranked, tuple(attempted))
    if len(ranked) > 1 and ranked[0].score - ranked[1].score <= ambiguity_score_gap:
        return MetadataLookupOutcome("ambiguous", ranked, tuple(attempted))
    return MetadataLookupOutcome("matched", ranked, tuple(attempted))


def _score_result(book: Book, result: MetadataResult, lookup_type: str) -> float:
    score = result.confidence
    if lookup_type == "isbn" and _isbn_matches(book, result):
        score = max(score, 0.98)
    if _clean_match(book.title) and _clean_match(book.title) == _clean_match(result.title):
        score += 0.05
    if _clean_match(book.primary_author_name) and _clean_match(book.primary_author_name) in {_clean_match(author) for author in result.authors}:
        score += 0.05
    return min(score, 1.0)


def _isbn_matches(book: Book, result: MetadataResult) -> bool:
    book_isbns = {normalize_isbn_query(value) for value in (book.isbn10, book.isbn13) if value}
    result_isbns = {normalize_isbn_query(value) for value in (result.isbn10, result.isbn13) if value}
    return bool(book_isbns & result_isbns)


def _clean_match(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())
