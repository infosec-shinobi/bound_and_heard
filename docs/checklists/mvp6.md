# MVP 6 Checklist

## Goal

Enrich books with external metadata while caching all provider responses locally and protecting manual edits.

## Source

Derived from `docs/ROADMAP.md` MVP 6 - Metadata Enrichment, with continuity from MVP 2 Libby imports, MVP 3 import review, MVP 4 scraping, and MVP 5 manual-first series tracking.

## Chunk 1 - Enrichment Data Model

- [x] Decide table shape for metadata cache and enrichment run history
- [x] Add provider response cache table keyed by provider, lookup type, normalized query, and response checksum
- [x] Add enrichment run/job table if needed for resumable bulk enrichment
- [x] Add per-book enrichment attribution fields only where needed
- [x] Preserve existing manual source fields and correction-event behavior
- [x] Add indexes for provider, lookup type, query, book, status, and timestamps
- [x] Add Alembic migration
- [x] Verify `alembic upgrade head`

## Chunk 2 - Provider Interfaces

- [x] Define provider-neutral metadata result object
- [x] Define provider client interface for ISBN and title/author lookup
- [x] Implement Open Library client
- [x] Implement Google Books client
- [x] Normalize provider response fields into common result shape
- [x] Capture raw provider responses for cache storage
- [x] Handle provider errors, missing results, malformed responses, and rate limits safely

## Chunk 3 - Metadata Cache

- [x] Store raw provider responses locally before applying metadata
- [x] Reuse cached responses for repeated identical lookups
- [x] Track provider, lookup type, normalized query, status, HTTP metadata if available, and fetched_at
- [x] Avoid repeated API calls when cache has a usable response
- [x] Add manual cache refresh option for admin users
- [x] Keep failed/empty responses cacheable enough to avoid tight retry loops

## Chunk 4 - Lookup Strategy

- [x] Prefer ISBN lookup when ISBN-10 or ISBN-13 exists
- [x] Fall back to title/author lookup when ISBN is missing or returns no useful result
- [x] Normalize ISBNs and title/author query strings consistently
- [x] Rank candidate results conservatively
- [x] Avoid applying low-confidence matches automatically
- [x] Surface ambiguous candidates for user review instead of silently choosing
- [x] Keep audiobook, ebook, and physical records distinct unless user explicitly edits them

## Chunk 5 - Fill-Empty-Fields Application

- [x] Apply enrichment only to empty fields by default
- [x] Fill cover image URL when empty
- [x] Fill page count when empty
- [x] Fill publication year/date when supported by schema
- [ ] Fill genre/category values when empty or absent
- [x] Fill publisher/ISBN fields only when empty and confidence is acceptable
- [x] Do not overwrite title, author, notes, rating, status, progress, completion date, or series assignments
- [x] Record metadata source attribution for applied fields

## Chunk 6 - Manual Overwrite Protection

- [x] Respect existing manual values and manual correction events
- [ ] Add explicit overwrite controls only if needed and clearly labeled
- [x] Prevent enrichment from replacing manually edited fields
- [x] Preserve Libby import attribution unless enrichment fills previously empty fields
- [x] Preserve scraped progress and reading events
- [x] Preserve MVP 5 series records, planned entries, and assignments

## Chunk 7 - Enrichment UI

- [x] Add protected enrichment entry point from book detail
- [x] Add protected bulk enrichment entry point from review or books list if practical
- [x] Show proposed metadata before applying ambiguous results
- [x] Show cache/provider/source context on enrichment results
- [x] Return clear success, skipped, and error messages
- [x] Keep read-only users able to view existing metadata without triggering enrichment
- [x] Keep all mutation actions protected by admin login

## Chunk 7.5 - Bulk Enrichment

- [x] Add protected bulk enrichment action from import review
- [x] Scope bulk enrichment to selected books when selection is provided
- [x] Support enriching current review-filter result set when no explicit selection is provided
- [x] Reuse cached provider responses and book-detail enrichment services
- [x] Return a clear summary of checked, updated, skipped, ambiguous, low-confidence, and error counts
- [x] Preserve review state; do not mark books reviewed automatically
- [x] Keep read-only users unable to trigger bulk enrichment
- [x] Avoid applying ambiguous or low-confidence matches automatically

## Chunk 8 - Import Review Integration

- [x] Add enrichment actions for imported books needing metadata cleanup
- [x] Make missing page count, cover URL, ISBN, publisher, and author filters work naturally with enrichment
- [x] Avoid marking books reviewed automatically after enrichment unless user chooses review action
- [x] Preserve manual review state and review notes
- [x] Make it easy to compare imported Libby metadata and enriched provider metadata

## Chunk 9 - Genre And Category Handling

- [ ] Decide schema for genres/categories if existing placeholder tables are not implemented
- [ ] Normalize provider categories into local labels
- [ ] Avoid duplicate genre/category labels by case-insensitive matching
- [ ] Attach genres/categories to books without overwriting manual labels
- [ ] Preserve raw provider category strings for traceability

## Chunk 10 - Series Metadata Research

- [ ] Research whether Open Library, Google Books, or another provider exposes usable series metadata
- [ ] Document provider limitations and confidence concerns
- [ ] Keep MVP 6 series behavior suggestion-only
- [ ] Do not auto-create series from enrichment metadata
- [ ] Do not overwrite manual MVP 5 series assignments or planned entries
- [ ] Capture follow-up recommendations for a future series-enrichment workflow

## Chunk 11 - Tests

- [x] Test enrichment/cache model and migration fields
- [x] Test provider response parsing for Open Library
- [x] Test provider response parsing for Google Books
- [x] Test ISBN lookup preference
- [x] Test title/author fallback lookup
- [x] Test cache hit avoids repeated provider call
- [x] Test empty/failed cache behavior
- [x] Test fill-empty-fields application
- [x] Test manual overwrite protection
- [x] Test enrichment does not overwrite Libby import attribution unexpectedly
- [x] Test enrichment does not alter reading events, scraped progress, or series assignments
- [x] Test ambiguous results are not silently applied
- [x] Test enrichment UI permissions and read-only behavior
- [x] Test import review integration
- [ ] Test genre/category normalization if implemented

## Chunk 12 - Documentation

- [ ] Update README with metadata enrichment workflow
- [ ] Document provider configuration and network behavior
- [ ] Document metadata cache behavior
- [ ] Document fill-empty-fields-only policy
- [ ] Document manual overwrite protection
- [ ] Document provider attribution and raw response preservation
- [ ] Update database documentation for enrichment/cache tables and genre/category fields
- [ ] Document series metadata research and future suggestion-only direction

## MVP 6 Done Criteria

- [ ] User can enrich a book by ISBN when an ISBN exists
- [ ] User can enrich a book by title/author when ISBN lookup is unavailable or unhelpful
- [ ] Provider responses are cached locally and reused
- [ ] Cover URL can be filled when empty
- [ ] Page count can be filled when empty
- [ ] Publication year/date can be filled when supported
- [ ] Genre/category values can be filled or attached when supported
- [ ] Manual edits are not silently overwritten
- [ ] Libby import data, scraped progress, reading events, and series assignments are preserved
- [ ] Ambiguous or low-confidence results are not silently applied
- [ ] Basic tests pass
