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

- [ ] Parse top-level `version`
- [ ] Parse `timeline` array
- [ ] Parse cover metadata
- [ ] Parse title text, share URL, and title ID
- [ ] Parse author
- [ ] Parse publisher
- [ ] Parse ISBN
- [ ] Parse timestamp
- [ ] Parse activity
- [ ] Parse details
- [ ] Parse library metadata
- [ ] Preserve each raw timeline item for source attribution

## Chunk 6 - Event-Level Deduplication

- [ ] Define stable Libby source event key
- [ ] Include title ID, timestamp, activity, library key, and format where available
- [ ] Store `source="libby"` and `source_event_id`
- [ ] Prevent duplicate reading events across overlapping exports
- [ ] Add tests for overlapping exports

## Chunk 7 - Book Creation And Update Logic

- [ ] Create books from Libby timeline entries when no matching local book exists
- [ ] Match/update existing Libby books by Libby title ID where available
- [ ] Use title/author/format fallback matching cautiously
- [ ] Fill empty fields from import data
- [ ] Avoid overwriting manual title, author, notes, rating, progress, or completion edits
- [ ] Store Libby identifiers and share URL on book records
- [ ] Set format from Libby cover metadata when available

## Chunk 8 - Reading Event Creation

- [ ] Map Libby activities to internal event types
- [ ] Convert Libby timestamps to timezone-aware datetimes
- [ ] Create borrowed events
- [ ] Create returned events where applicable
- [ ] Create started/progress/completed events when inferable
- [ ] Preserve raw event data
- [ ] Include import summary counts for created/skipped events

## Chunk 9 - Import Summary Page

- [ ] Add import detail/summary page
- [ ] Show filename, checksum, status, and import time
- [ ] Show row count
- [ ] Show books created
- [ ] Show books updated
- [ ] Show events created
- [ ] Show duplicate events skipped
- [ ] Show duplicate file status
- [ ] Link from summary to imported/updated books where simple

## Chunk 10 - Manual Overwrite Protection

- [ ] Track source for imported book metadata
- [ ] Do not overwrite manual edits by default
- [ ] Fill empty fields only unless an explicit overwrite path is added later
- [ ] Keep manual correction events intact
- [ ] Add tests proving manual edits survive re-imports

## Chunk 11 - Tests And Documentation

- [ ] Test upload requires write access
- [ ] Test valid Libby JSON import creates import record
- [ ] Test raw JSON is preserved
- [ ] Test duplicate file detection
- [ ] Test event-level deduplication
- [ ] Test book creation/update behavior
- [ ] Test manual overwrite protection
- [ ] Test import summary counts
- [ ] Update README with Libby import instructions

## MVP 2 Done Criteria

- [ ] User can upload a Libby JSON export after admin login
- [ ] Raw JSON is preserved locally
- [ ] File checksum is stored
- [ ] Duplicate files are detected
- [ ] Overlapping exports do not duplicate reading events
- [ ] Imported Libby books appear in the book list
- [ ] Imported reading events appear on book detail pages
- [ ] Manual edits are not silently overwritten
- [ ] Import summary shows useful created/skipped counts
- [ ] Dark/light mode toggle works
- [ ] Current local user's display name can be updated from a protected settings page
- [ ] Basic tests pass
