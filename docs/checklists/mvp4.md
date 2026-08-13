# MVP 4 Checklist

## Goal

Use Playwright to retrieve progress data for imported Libby books, including partial progress where available, while avoiding unnecessary re-scrapes and isolating per-book failures.

## Source

Derived from `docs/ROADMAP.md` MVP 4 - Libby Progress Scraping, with continuity from MVP 2 Libby imports and MVP 3 import review, manual correction events, and manual overwrite protection.

## Chunk 1 - Scraping Data Model

- [x] Decide whether scrape jobs belong in new tables or existing import/job tables
- [x] Add scrape job model with source, status, created_at, started_at, finished_at, and summary fields
- [x] Add scrape job item model with book_id, status, attempts, timestamps, and error fields
- [x] Track latest borrow timestamp or scrape eligibility metadata per book/item
- [x] Add raw snapshot model or file reference for preserved scrape output
- [x] Add indexes for queue selection and per-book lookup
- [x] Add Alembic migration if schema changes
- [x] Verify `alembic upgrade head`

## Chunk 2 - Playwright Dependency And Browser Profile

- [x] Add Playwright dependency and installation notes
- [x] Choose persistent browser profile directory
- [x] Add config for browser profile path if needed
- [x] Ensure profile directory stays untracked
- [x] Add startup or command documentation for installing browsers
- [x] Avoid storing Libby credentials in the application database

## Chunk 3 - Manual Libby Login Flow

- [x] Add protected page or command to open a persistent Libby browser session
- [x] Let the user complete Libby login manually
- [x] Detect or document how to verify that the session is logged in
- [x] Handle missing or expired sessions with a clear error
- [x] Keep read-only users blocked from starting login/session actions
- [x] Document that browser profile cookies are local machine state

## Chunk 4 - Scrape Job Creation UI

- [x] Add protected route to create a Libby progress scrape job
- [x] Let the user preview candidate books before creating a job
- [x] Include only imported Libby books with enough source context to scrape
- [x] Exclude archived, ignored, or reviewed-out records where appropriate
- [x] Show count of queued, skipped, and ineligible books
- [x] Add navigation entry or review-page action for scraping
- [x] Return useful feedback when no books are eligible

## Chunk 5 - Scrape Queue And Job Items

- [x] Create per-book scrape job items when a job starts
- [x] Track item statuses: queued, running, succeeded, failed, skipped
- [x] Process one item at a time by default
- [x] Prevent duplicate active scrape jobs when unsafe
- [x] Preserve job progress if the process stops mid-job
- [x] Allow viewing job detail and item statuses
- [x] Ensure one failed item does not fail the entire job

## Chunk 6 - Skip Logic

- [x] Define latest borrow timestamp source for each book
- [x] Store last scraped borrow timestamp or equivalent marker
- [x] Skip books whose latest borrow timestamp has already been scraped
- [x] Allow force re-scrape when explicitly requested
- [x] Show skipped items in job summary
- [x] Test unchanged books are not re-scraped
- [x] Allow cancelling pending or running scrape jobs
- [x] add ability to configure scrape job on specific books

## Chunk 7 - Polite Scraping Delays And Safety

- [x] Add randomized 5-15 second delay between book pages
- [x] Keep delay logic testable without slowing tests
- [x] Limit scraping to user-triggered jobs
- [x] Add timeout handling for page loads/selectors
- [x] Capture enough failure detail to diagnose selector/session problems
- [x] Avoid tight retry loops

## Chunk 8 - Raw Snapshot Preservation

- [x] Save raw page HTML, extracted text, or structured scrape payload per item
- [x] Store snapshot checksum/path/reference on scrape item
- [x] Keep snapshots under a configured local data directory
- [x] Preserve failed-item snapshots when useful
- [x] Avoid committing raw snapshots
- [x] Show snapshot reference on scrape job detail page

## Chunk 9 - Progress Parsing

- [x] Identify Libby progress text/selectors for ebooks and audiobooks
- [x] Parse partial progress percent when available
- [x] Parse completed progress when available
- [x] Parse page or duration progress if available
- [x] Normalize parsed values into `BookProgress` or equivalent fields
- [x] Preserve source attribution as `libby` or scrape-specific source
- [x] Add parser tests using saved fixture snippets

## Chunk 10 - Completion Inference And Manual Protection

- [x] Infer approximate completion date only when exact completion date is unavailable
- [x] Do not overwrite manually corrected completion dates
- [x] Do not overwrite manually corrected progress unless explicitly requested later
- [x] Update completion status only when it does not conflict with manual corrections
- [x] Create manual or scrape-attributed events where appropriate
- [x] Preserve existing Libby import events and manual correction events
- [x] Test manual corrections survive scraping updates

## Chunk 11 - Failure Handling And Retry

- [ ] Capture per-book failure reason and traceback or selector context
- [ ] Mark failed items without failing the whole job
- [ ] Add retry action for failed items
- [ ] Add skip action for failed items
- [ ] Track attempt count and last attempted timestamp
- [ ] Show failed/skipped counts in job summary
- [ ] Test failed item isolation and retry/skip behavior

## Chunk 12 - Tests

- [ ] Test scrape job creation creates expected job and item records
- [ ] Test read-only users cannot create or run scrape jobs
- [ ] Test persistent profile path/config behavior
- [ ] Test skip logic for unchanged latest borrow timestamp
- [ ] Test forced re-scrape bypasses skip logic if implemented
- [ ] Test randomized delay logic without real waiting
- [ ] Test raw snapshot preservation references
- [ ] Test progress parser for partial progress
- [ ] Test completion inference and manual overwrite protection
- [ ] Test per-book failure does not fail entire job
- [ ] Test retry or skip failed scrape items

## Chunk 13 - Documentation

- [ ] Update README with Libby progress scraping workflow
- [ ] Document Playwright installation and browser profile setup
- [ ] Document manual Libby login expectations
- [ ] Document skip logic and force re-scrape behavior
- [ ] Document raw snapshot storage and privacy considerations
- [ ] Update database documentation for scrape job/item/snapshot fields

## MVP 4 Done Criteria

- [ ] User can authenticate Libby in a persistent local browser profile
- [ ] User can create a progress scrape job for eligible imported Libby books
- [ ] Scrape jobs create per-book items and process them independently
- [ ] The scraper waits 5-15 seconds between pages
- [ ] Unchanged books are skipped using latest borrow timestamp logic
- [ ] Raw scrape snapshots are preserved locally
- [ ] Partial progress is captured where Libby exposes it
- [ ] Approximate completion dates are inferred only when safe
- [ ] Completion status updates respect manual corrections
- [ ] Failed book scrape items do not fail the entire job
- [ ] Failed items can be retried or skipped
- [ ] Basic tests pass

## Future MVP - Read Count And Lifetime Enjoyment

- [ ] Let users manually record prior reads/listens so `read_count` is useful beyond current imported/scraped state
- [ ] Decide how to distinguish Libby "picked up" session count from true completed read/listen count
- [ ] Investigate title timeline + duration heuristics for repeat reads, e.g. Storm Front / Libby title ID 220325 where journey duration can exceed title duration
- [ ] Surface lifetime enjoyed time separately from current-loan progress when repeat-read detection is available
