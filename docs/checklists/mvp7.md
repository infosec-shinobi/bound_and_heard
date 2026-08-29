# MVP 7 Checklist

## Goal

Show trends in reading and listening behavior and generate personal quarterly/yearly recap pages.

## Source

Derived from `docs/ROADMAP.md` MVP 7 - Analytics and Recaps, with continuity from MVP 2 Libby imports, MVP 3 import review, MVP 4 scraping, MVP 5 series tracking, and MVP 6 metadata enrichment.

## Chunk 1 - Analytics Scope And Definitions

- [x] Define which records count as consumed books for analytics
- [x] Define period boundaries for month, quarter, year, and all-time views
- [x] Define how completed books are counted from `reading_events` and `books.status`
- [x] Define how re-reads and re-listens are derived from completed events
- [x] Define how prior read/listen entries affect totals and recaps
- [x] Define page totals when page count is missing or format is audiobook
- [x] Define audiobook-hour totals when audio duration is missing or format is ebook/physical
- [x] Define partial-progress metrics for in-progress and abandoned books
- [x] Define how Libby `picked up` session counts differ from completed read/listen counts
- [x] Document analytics assumptions before building UI

## Chunk 2 - Analytics Service Layer

- [x] Add service functions for period range calculation
- [x] Add service function for books completed by month
- [x] Add service function for books completed by quarter/year
- [x] Add service function for format breakdown
- [x] Add service function for top authors
- [x] Add service function for top genres
- [x] Add service function for pages read when known
- [x] Add service function for audiobook hours when known
- [x] Add service function for partial progress summaries
- [x] Add service function for repeat read/listen counts
- [x] Keep service functions independent from templates and route state
- [x] Add tests for analytics calculations and date boundaries

## Chunk 3 - Prior Read/Listen Entry Workflow

- [x] Decide whether prior consumption is stored as `reading_events` or a dedicated table
- [x] Add schema changes if current `reading_events` cannot represent prior consumption cleanly
- [x] Add protected UI for adding prior read/listen entries to a book
- [x] Support prior completion date when known
- [x] Decide approximate prior period support is deferred until there is a concrete need
- [x] Support format-specific prior read/listen entries
- [x] Ensure prior entries increment true read/listen counts
- [x] Ensure prior entries do not corrupt Libby import or scrape history
- [x] Add delete/re-add controls for prior entries instead of full event editing
- [x] Add tests for prior entry creation, counting, permissions, and source attribution

## Chunk 4 - Lifetime Enjoyed Time

- [x] Define lifetime enjoyed time separately from current-loan progress
- [x] Use Libby scraped `enjoyed_seconds` when available
- [x] Avoid treating Libby `picked up` session count as true read/listen count
- [x] Decide how manual audiobook completions contribute to lifetime enjoyed time when duration is known
- [x] Show lifetime enjoyed time on book detail where useful
- [x] Include lifetime enjoyed time in analytics summaries
- [x] Preserve current-loan progress values separately from lifetime totals
- [x] Add tests for enjoyed time aggregation and display

## Chunk 5 - Repeat Read/Listen Heuristics

- [x] Identify timeline and duration signals that suggest repeated consumption
- [x] Derive repeat counts from completed events before using weaker heuristics
- [x] Avoid inferring true completion from Libby `picked up` session count alone
- [x] Detect likely repeated Libby borrows/listens conservatively
- [x] Surface heuristic-derived repeat counts as lower confidence if displayed
- [x] Avoid automatically creating completion events from weak heuristic signals
- [x] Add tests for repeat-count derivation and false-positive prevention

## Chunk 6 - Analytics UI Dashboard

- [ ] Add analytics route and navigation entry
- [ ] Show books by month
- [ ] Show books completed by selected period
- [ ] Show format breakdown
- [ ] Show top authors
- [ ] Show top genres
- [ ] Show pages read when known
- [ ] Show audiobook hours when known
- [ ] Show partial-progress summaries
- [ ] Show re-read and re-listen counts
- [ ] Show lifetime enjoyed time where available
- [ ] Add period filters for year, quarter, and all-time where useful
- [ ] Keep dashboard usable on desktop and mobile
- [ ] Keep analytics pages read-only for non-admin users

## Chunk 7 - Series Analytics

- [ ] Add service function for series activity in a selected period
- [ ] Count completed series entries using MVP 5/MVP 6 completion rules
- [ ] Include collection/range coverage without inflating totals
- [ ] Identify active series based on recent completions or progress
- [ ] Identify completed, paused, abandoned, and unknown series counts
- [ ] Show favorite or most-active series candidates
- [ ] Show next unread series book where relevant
- [ ] Add tests for series analytics, planned entries, and collection ranges

## Chunk 8 - Recap Data Model And Generation

- [ ] Decide final `recaps` table fields and generated artifact storage
- [ ] Add Alembic migration if recap storage needs to change
- [ ] Add recap generation service for quarterly recaps
- [ ] Add recap generation service for yearly recaps
- [ ] Store generated recap metadata and output path
- [ ] Avoid overwriting existing generated recaps unless explicitly requested
- [ ] Make recap generation deterministic for the same source data when practical
- [ ] Add tests for recap generation, persistence, and overwrite protection
- [ ] Verify `alembic upgrade head` if migrations are added

## Chunk 9 - Recap Pages

- [ ] Add quarterly recap page
- [ ] Add yearly recap page
- [ ] Show books completed
- [ ] Show favorite author
- [ ] Show favorite genre
- [ ] Show favorite series
- [ ] Show longest book
- [ ] Show most active month
- [ ] Show format mix
- [ ] Show pages read and audiobook hours when known
- [ ] Show re-read/re-listen highlights when available
- [ ] Show series progress highlights
- [ ] Clearly label missing or estimated metrics
- [ ] Keep recap pages usable on desktop and mobile

## Chunk 10 - Recap Export

- [ ] Decide supported export formats for MVP 7: Markdown, HTML, or both
- [ ] Add export service for selected recap format
- [ ] Preserve exported files under local data/export storage
- [ ] Add protected export action for generated recaps if exports create files
- [ ] Keep viewing existing recap pages read-only where possible
- [ ] Include enough metadata in exports to identify period and generated date
- [ ] Add tests for export content and permissions

## Chunk 11 - Permissions And Safety

- [ ] Keep analytics viewing available to read-only users
- [ ] Protect prior entry mutations behind admin login
- [ ] Protect recap generation behind admin login
- [ ] Protect recap overwrite/export mutations behind admin login when they write files or database rows
- [ ] Preserve imported Libby history, scraped progress, metadata enrichment data, and series assignments during analytics/recap generation
- [ ] Avoid destructive recomputation of source data
- [ ] Return clear UI messages for generated, skipped, overwritten, and failed recap actions
- [ ] Add tests for read-only access and admin-only mutations

## Chunk 12 - Tests

- [ ] Test period boundary calculations
- [ ] Test monthly completed-book counts
- [ ] Test quarterly and yearly completed-book counts
- [ ] Test format breakdown
- [ ] Test top author ranking
- [ ] Test top genre ranking
- [ ] Test pages-read totals with missing page counts
- [ ] Test audiobook-hour totals with missing durations
- [ ] Test partial-progress summaries
- [ ] Test re-read and re-listen counts from completed events
- [ ] Test prior read/listen entries
- [ ] Test lifetime enjoyed time aggregation
- [ ] Test repeat-read/listen heuristic safety
- [ ] Test series activity and favorite-series calculations
- [ ] Test recap generation for quarter and year
- [ ] Test recap export if implemented
- [ ] Test permissions for analytics, prior entries, generation, and exports
- [ ] Verify full `pytest` pass

## Chunk 13 - Documentation

- [ ] Update README with analytics dashboard workflow
- [ ] Document recap generation workflow
- [ ] Document prior read/listen entry behavior
- [ ] Document lifetime enjoyed time versus current progress
- [ ] Document re-read/re-listen counting rules
- [ ] Document Libby `picked up` count limitations
- [ ] Document recap export behavior and storage location
- [ ] Update database documentation for recap/prior-entry schema changes
- [ ] Update architecture documentation if analytics or recap services materially change

## MVP 7 Done Criteria

- [ ] User can view books completed by month
- [ ] User can view format breakdown
- [ ] User can view top authors
- [ ] User can view top genres
- [ ] User can view books completed by selected period
- [ ] User can view audiobook hours when known
- [ ] User can view pages read when known
- [ ] User can view partial-progress summaries
- [ ] User can see re-read and re-listen counts derived from completed events
- [ ] User can add prior read/listen entries for books consumed before tracking began
- [ ] Lifetime enjoyed time is shown separately from current-loan progress
- [ ] Libby `picked up` session count is not treated as true completed read/listen count
- [ ] User can view series activity
- [ ] User can generate a quarterly recap page
- [ ] User can generate a yearly recap page
- [ ] Recap shows favorite author, favorite genre, favorite series, longest book, most active month, and format mix
- [ ] User can export a recap to Markdown or HTML
- [ ] Analytics and recap generation preserve source data and manual edits
- [ ] Basic tests pass
