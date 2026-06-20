# MVP 2 Checklist

## Goal

Import Libby timeline JSON exports and normalize the data into local tables without duplicating overlapping historical events. Also carry forward MVP 1 user settings/theme items before adding more import-heavy workflows.

## Source

Derived from `docs/ROADMAP.md` MVP 2 - Libby JSON Import.

## Chunk 1 - Carry-Forward User Settings

- [x] Add protected settings/profile route
- [x] Add settings/profile page
- [x] Allow updating the current local user's display name
- [x] Keep `BOUND_AND_HEARD_DEFAULT_USER_NAME` as first-run bootstrap only
- [x] Add tests proving bootstrap does not overwrite an existing display name
- [x] Add dark/light mode toggle switch
- [x] Persist theme preference locally or in the user profile
- [x] Apply theme preference in `base.html`
- [x] Render an HTML login page instead of JSON for protected browser routes
- [x] Redirect back to the protected page after admin login

## Chunk 2 - Import Data Model

- [x] Add `Import` model
- [x] Add `ImportFile` model if raw file metadata needs separate storage
- [x] Add fields for source, filename, checksum, imported_at, row_count, status, and summary
- [x] Add raw file path or raw JSON preservation reference
- [x] Add indexes/constraints for duplicate detection
- [x] Add Alembic migration
- [x] Verify `alembic upgrade head`

## Chunk 3 - Libby Upload Form

- [x] Add imports route module
- [x] Add password-protected Libby JSON upload form
- [x] Accept `.json` uploads
- [x] Validate that uploaded content is JSON
- [x] Save uploaded raw JSON under `data/imports/libby/`
- [x] Keep read-only users blocked from upload
- [x] Add navigation entry for imports

## Chunk 4 - Checksum And Duplicate File Detection

- [x] Calculate file checksum before processing
- [x] Store checksum on import record
- [x] Detect exact duplicate files
- [x] Skip duplicate file processing safely
- [x] Show duplicate status in the UI
- [x] Preserve the original raw JSON for non-duplicate imports

## Chunk 5 - Libby JSON Parser

- [x] Parse top-level `version`
- [x] Parse `timeline` array
- [x] Parse cover metadata
- [x] Parse title text, share URL, and title ID
- [x] Parse author
- [x] Parse publisher
- [x] Parse ISBN
- [x] Parse timestamp
- [x] Parse activity
- [x] Parse details
- [x] Parse library metadata
- [x] Preserve each raw timeline item for source attribution

## Chunk 6 - Event-Level Deduplication

- [x] Define stable Libby source event key
- [x] Include title ID, timestamp, activity, library key, and format where available
- [x] Store `source="libby"` and `source_event_id`
- [x] Prevent duplicate reading events across overlapping exports
- [x] Add tests for overlapping exports

## Chunk 7 - Book Creation And Update Logic

- [x] Create books from Libby timeline entries when no matching local book exists
- [x] Match/update existing Libby books by Libby title ID where available
- [x] Use title/author/format fallback matching cautiously
- [x] Fill empty fields from import data
- [x] Avoid overwriting manual title, author, notes, rating, progress, or completion edits
- [x] Store Libby identifiers and share URL on book records
- [x] Set format from Libby cover metadata when available

## Chunk 8 - Reading Event Creation

- [x] Map Libby activities to internal event types
- [x] Convert Libby timestamps to timezone-aware datetimes
- [x] Create borrowed events
- [x] Create returned events where applicable
- [x] Create started/progress/completed events when inferable
- [x] Preserve raw event data
- [x] Include import summary counts for created/skipped events

## Chunk 9 - Import Summary Page

- [x] Add import detail/summary page
- [x] Show filename, checksum, status, and import time
- [x] Show row count
- [x] Show books created
- [x] Show books updated
- [x] Show events created
- [x] Show duplicate events skipped
- [x] Show duplicate file status
- [x] Link from summary to imported/updated books where simple

## Chunk 10 - Manual Overwrite Protection

- [x] Track source for imported book metadata
- [x] Do not overwrite manual edits by default
- [x] Fill empty fields only unless an explicit overwrite path is added later
- [x] Keep manual correction events intact
- [x] Add tests proving manual edits survive re-imports

## Chunk 11 - Tests And Documentation

- [x] Test upload requires write access
- [x] Test valid Libby JSON import creates import record
- [x] Test raw JSON is preserved
- [x] Test duplicate file detection
- [x] Test event-level deduplication
- [x] Test book creation/update behavior
- [x] Test manual overwrite protection
- [x] Test import summary counts
- [x] Update README with Libby import instructions

## MVP 2 Done Criteria

- [x] User can upload a Libby JSON export after admin login
- [x] Raw JSON is preserved locally
- [x] File checksum is stored
- [x] Duplicate files are detected
- [x] Overlapping exports do not duplicate reading events
- [x] Imported Libby books appear in the book list
- [x] Imported reading events appear on book detail pages
- [x] Manual edits are not silently overwritten
- [x] Import summary shows useful created/skipped counts
- [x] Dark/light mode toggle works
- [x] Current local user's display name can be updated from a protected settings page
- [x] Basic tests pass
