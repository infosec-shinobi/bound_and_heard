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
- [x] Fill genre/category values when empty or absent
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

- [x] Decide schema for genres/categories if existing placeholder tables are not implemented
- [x] Normalize provider categories into local labels
- [x] Avoid duplicate genre/category labels by case-insensitive matching
- [x] Attach genres/categories to books without overwriting manual labels
- [x] Preserve raw provider category strings for traceability

## Chunk 10 - Series Metadata Research

- [x] Research whether Open Library, Google Books, or another provider exposes usable series metadata
- [x] Document provider limitations and confidence concerns
- [x] Keep MVP 6 series behavior suggestion-only
- [x] Do not auto-create series from enrichment metadata
- [x] Do not overwrite manual MVP 5 series assignments or planned entries
- [x] Capture follow-up recommendations for a future series-enrichment workflow

## Chunk 10.5 - Libby Series Hints

- [x] Parse Libby reading journey series links like `/shelf/series-503231/page-1`
- [x] Extract Libby series key, raw series URL, raw label, series name, and numeric position when available
- [x] Store Libby-derived series hints without immediately changing local `series` or `series_books`
- [x] Show Libby series suggestions on Libby-related book detail and import review rows
- [x] Add admin-only action to apply a Libby series suggestion to a book
- [x] Match existing local series by normalized name before offering to create a new series
- [x] Create or assign series only after explicit admin confirmation
- [x] Do not overwrite existing manual series assignments, planned entries, positions, or notes without explicit choice
- [x] Keep non-Libby books eligible for external enrichment without requiring Libby series data
- [x] Keep external provider series metadata suggestion-only and lower confidence than Libby journey hints
- [x] Add tests for parsing, storage, display, permissions, and manual-apply behavior

## Chunk 10.6 - Manual Book Enrichment

- [ ] Ensure manually entered books can use metadata enrichment from book detail
- [ ] Add a missing-metadata workflow for manual books if review filters remain Libby-focused
- [ ] Prefer ISBN lookup for manual books when ISBN is present
- [ ] Fall back to title/author lookup for manual books when ISBN is missing or unhelpful
- [ ] Fill only empty supported fields on manual books
- [ ] Preserve manual title, author, notes, rating, status, progress, completion date, genres, and series assignments
- [ ] Surface ambiguous or low-confidence manual-book matches for review instead of applying automatically
- [ ] Show provider/cache/source context for manual-book enrichment results
- [ ] Keep all manual-book enrichment mutations admin-only
- [ ] Add tests for manual-book enrichment, fallback lookup, overwrite protection, and permissions

## Chunk 10.7 - Libby Series Population

- [x] Parse Libby series page HTML
- [x] Extract series page title, listed books, authors, formats, Libby title IDs or title URLs when available
- [x] Extract or infer series positions when Libby exposes ordering
- [x] Match parsed Libby series entries to existing local books by Libby title ID first, then conservative title/author/format matching
- [x] Preview planned series changes before applying them
- [x] Add admin-only action to populate an existing local series from a Libby series hint/page
- [x] Create `series_books` rows for matched existing books only when not already assigned to that series
- [x] Create planned entries for unmatched Libby series titles only after explicit confirmation
- [x] Preserve existing manual series entries, positions, notes, and planned entries
- [x] Avoid duplicate planned entries by normalized title/author/format/position matching
- [x] Store raw Libby series page context or parse metadata for traceability
- [x] Add tests for parsing, matching, preview, permissions, duplicate avoidance, and manual preservation
- [x] Parse Libby collection ranges such as `1-3 in series`
- [x] Track collection range coverage without inflating series progress totals
- [x] Count a completed collection as satisfying individual works covered by its range

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
- [x] Test genre/category normalization if implemented

## Chunk 12 - Documentation

- [x] Update README with metadata enrichment workflow
- [x] Document provider configuration and network behavior
- [x] Document metadata cache behavior
- [x] Document fill-empty-fields-only policy
- [x] Document manual overwrite protection
- [x] Document provider attribution and raw response preservation
- [x] Update database documentation for enrichment/cache tables and genre/category fields
- [x] Document series metadata research and future suggestion-only direction

## MVP 6 Done Criteria

- [x] User can enrich a book by ISBN when an ISBN exists
- [x] User can enrich a book by title/author when ISBN lookup is unavailable or unhelpful
- [x] Provider responses are cached locally and reused
- [x] Cover URL can be filled when empty
- [x] Page count can be filled when empty
- [x] Publication year/date can be filled when supported
- [x] Genre/category values can be filled or attached when supported
- [x] Manual edits are not silently overwritten
- [x] Libby import data, scraped progress, reading events, and series assignments are preserved
- [x] Ambiguous or low-confidence results are not silently applied
- [x] Basic tests pass
