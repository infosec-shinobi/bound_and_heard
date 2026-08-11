# MVP 3 Checklist

## Goal

Provide a fast workflow for reviewing imported Libby data before relying on it for scraping, analytics, and recaps. MVP 3 should make it easy to find incomplete or suspicious imported records and correct them without opening every book detail page.

## Source

Derived from `docs/ROADMAP.md` MVP 3 - Import Review and Cleanup, with continuity from MVP 2 import records, Libby book creation, reading events, and manual overwrite protection.

## Chunk 1 - Review State And Cleanup Data Model

- [x] Decide whether review state belongs on `books` or a separate review table
- [x] Add fields for review status if needed: needs_review, reviewed, ignored, duplicate_candidate
- [x] Add reviewed_at or ignored_at if useful
- [x] Add reviewed_note or review_reason if useful
- [x] Keep imported metadata source fields intact
- [x] Add indexes for review filters
- [x] Add Alembic migration if schema changes
- [x] Verify `alembic upgrade head`

## Chunk 2 - Imported Books Needing Review Page

- [x] Add review route module or extend books route cleanly
- [x] Add protected/read-only review page for imported books
- [x] List imported Libby books that need cleanup
- [x] Show title, author, format, status, progress, page count, audio duration, completion date, and import/source indicators
- [x] Link each row to the book detail page
- [x] Add navigation entry for review/cleanup
- [x] Add empty state when no imported books need review

## Chunk 3 - Missing Core Metadata Filters

- [x] Add filter for missing page count
- [x] Add filter for missing audio duration
- [x] Add filter for missing author
- [x] Add filter for missing publisher
- [x] Add filter for missing ISBN
- [x] Add filter for missing cover URL
- [x] Allow combining filters
- [x] Preserve filter state in query params

## Chunk 4 - Ambiguous Or Suspicious Metadata Filters

- [x] Add filter for unknown format
- [x] Add filter for unknown status
- [x] Add filter for missing Libby title ID
- [x] Add filter for imported books with title fallback values such as `Untitled Libby Book`
- [x] Add filter for books without any reading events
- [x] Add filter for completed status without completion date
- [x] Add filter for progress/status mismatch where simple to detect

## Chunk 5 - Duplicate Candidate Detection

- [x] Define duplicate candidate rules for review UI
- [x] Detect same Libby title ID and format across multiple local books
- [x] Detect same normalized title, author, and format
- [x] Detect same ISBN and format across multiple local books
- [x] Keep audiobook and ebook records separate unless identifiers strongly indicate a duplicate
- [x] Add duplicate candidate filter
- [x] Show why each candidate was flagged
- [x] Do not auto-merge duplicate candidates in MVP 3

## Chunk 6 - Quick Status Correction

- [ ] Add protected quick status update action from review rows
- [ ] Support want_to_read, borrowed, started, completed, abandoned, unknown
- [ ] Validate supported statuses
- [ ] Preserve manual overwrite protections
- [ ] Create a manual correction event when status changes
- [ ] Keep read-only users blocked from quick corrections
- [ ] Return to the same filtered review page after save

## Chunk 7 - Quick Progress Correction

- [ ] Add protected quick progress percent update action
- [ ] Validate 0-100 percent values
- [ ] Allow clearing manual progress when appropriate
- [ ] Create a manual correction event when progress changes
- [ ] Show validation errors without losing filter context
- [ ] Keep imported progress/source records intact unless explicitly changed later

## Chunk 8 - Quick Completion Date Correction

- [ ] Add protected quick completion date update action
- [ ] Validate ISO date input
- [ ] Allow clearing completion date when appropriate
- [ ] Create a manual correction event when completion date changes
- [ ] Consider setting status to completed only when user explicitly chooses that status
- [ ] Return to the same filtered review page after save

## Chunk 9 - Quick Archive Or Ignore Controls

- [ ] Add protected archive action from review rows
- [ ] Add protected restore action or link where useful
- [ ] Add ignore/reviewed action if review state exists
- [ ] Keep ignored books out of default review results
- [ ] Preserve book records, events, progress, and import attribution
- [ ] Create a manual correction event or review note where useful

## Chunk 10 - Review Workflow UX

- [ ] Add bulk-friendly table layout for fast scanning
- [ ] Keep quick correction controls compact on desktop
- [ ] Ensure review page works on mobile
- [ ] Add visible active filter chips or summary
- [ ] Add reset filters link
- [ ] Add per-row source/import context where simple
- [ ] Add clear success/error messages after quick actions

## Chunk 11 - Tests

- [ ] Test review page requires write access for mutations but remains readable if intended
- [ ] Test imported books needing review page lists imported Libby books
- [ ] Test missing page count filter
- [ ] Test missing audio duration filter
- [ ] Test missing or ambiguous metadata filters
- [x] Test duplicate candidate detection
- [ ] Test quick status correction creates manual correction event
- [ ] Test quick progress correction creates manual correction event
- [ ] Test quick completion date correction creates manual correction event
- [ ] Test archive/ignore controls preserve records and events
- [ ] Test filter context is preserved after quick actions
- [ ] Test manual edits still survive later imports

## Chunk 12 - Documentation

- [ ] Update README with import review workflow
- [ ] Document what counts as needing review
- [ ] Document duplicate candidate behavior and no auto-merge policy
- [ ] Document quick correction behavior and manual correction events
- [ ] Update any relevant database documentation for review state fields

## MVP 3 Done Criteria

- [ ] User can open an imported-books review page
- [ ] User can filter imported books missing page count or audio duration
- [ ] User can filter imported books missing or suspicious metadata
- [ ] User can identify duplicate candidates without automatic merging
- [ ] User can quickly correct status from the review workflow
- [ ] User can quickly correct progress from the review workflow
- [ ] User can quickly correct completion date from the review workflow
- [ ] User can archive or ignore records from the review workflow
- [ ] Quick corrections create manual correction events
- [ ] Manual edits and correction events remain intact after later imports
- [ ] Basic tests pass
