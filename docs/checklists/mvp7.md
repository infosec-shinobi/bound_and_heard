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

- [x] Add analytics route and navigation entry
- [x] Show books by month
- [x] Show books completed by selected period
- [x] Show format breakdown
- [x] Show top authors
- [x] Show top genres
- [x] Show pages read when known
- [x] Show audiobook hours when known
- [x] Show partial-progress summaries
- [x] Show re-read and re-listen counts
- [x] Show lifetime enjoyed time where available
- [x] Add period filters for year, quarter, and all-time where useful
- [x] Keep dashboard usable on desktop and mobile
- [x] Keep analytics pages read-only for non-admin users

## Chunk 7 - Series Analytics

- [x] Add service function for series activity in a selected period
- [x] Count completed series entries using MVP 5/MVP 6 completion rules
- [x] Include collection/range coverage without inflating totals
- [x] Identify active series based on recent completions or progress
- [x] Identify completed, paused, abandoned, and unknown series counts
- [x] Show favorite or most-active series candidates
- [x] Show next unread series book where relevant
- [x] Add tests for series analytics, planned entries, and collection ranges

## Chunk 8 - Recap Data Model And Generation

- [x] Decide final `recaps` table fields and generated artifact storage
- [x] Add Alembic migration if recap storage needs to change
- [x] Add recap generation service for quarterly recaps
- [x] Add recap generation service for yearly recaps
- [x] Store generated recap metadata and output path
- [x] Avoid overwriting existing generated recaps unless explicitly requested
- [x] Make recap generation deterministic for the same source data when practical
- [x] Add tests for recap generation, persistence, and overwrite protection
- [x] Verify `alembic upgrade head` if migrations are added

## Chunk 9 - Recap Pages

- [x] Add quarterly recap page
- [x] Add yearly recap page
- [x] Show books completed
- [x] Show favorite author
- [x] Show favorite genre
- [x] Show favorite series
- [x] Show longest book
- [x] Show most active month
- [x] Show format mix
- [x] Show pages read and audiobook hours when known
- [x] Show re-read/re-listen highlights when available
- [x] Show series progress highlights
- [x] Clearly label missing or estimated metrics
- [x] Keep recap pages usable on desktop and mobile

## Chunk 10 - Recap Export

- [x] Decide supported export formats for MVP 7: Markdown, HTML, or both
- [x] Add export service for selected recap format
- [x] Preserve exported files under local data/export storage
- [x] Add protected export action for generated recaps if exports create files
- [x] Keep viewing existing recap pages read-only where possible
- [x] Include enough metadata in exports to identify period and generated date
- [x] Add tests for export content and permissions

## Chunk 11 - Permissions And Safety

- [x] Keep analytics viewing available to read-only users
- [x] Protect prior entry mutations behind admin login
- [x] Protect recap generation behind admin login
- [x] Protect recap overwrite/export mutations behind admin login when they write files or database rows
- [x] Preserve imported Libby history, scraped progress, metadata enrichment data, and series assignments during analytics/recap generation
- [x] Avoid destructive recomputation of source data
- [x] Return clear UI messages for generated, skipped, overwritten, and failed recap actions
- [x] Add tests for read-only access and admin-only mutations

## Chunk 12 - Tests

- [x] Test period boundary calculations
- [x] Test monthly completed-book counts
- [x] Test quarterly and yearly completed-book counts
- [x] Test format breakdown
- [x] Test top author ranking
- [x] Test top genre ranking
- [x] Test pages-read totals with missing page counts
- [x] Test audiobook-hour totals with missing durations
- [x] Test partial-progress summaries
- [x] Test re-read and re-listen counts from completed events
- [x] Test prior read/listen entries
- [x] Test lifetime enjoyed time aggregation
- [x] Test repeat-read/listen heuristic safety
- [x] Test series activity and favorite-series calculations
- [x] Test recap generation for quarter and year
- [x] Test recap export if implemented
- [x] Test permissions for analytics, prior entries, generation, and exports
- [x] Verify full `pytest` pass

## Chunk 13 - Documentation

- [x] Update README with analytics dashboard workflow
- [x] Document recap generation workflow
- [x] Document prior read/listen entry behavior
- [x] Document lifetime enjoyed time versus current progress
- [x] Document re-read/re-listen counting rules
- [x] Document Libby `picked up` count limitations
- [x] Document recap export behavior and storage location
- [x] Update database documentation for recap/prior-entry schema changes
- [x] Update architecture documentation if analytics or recap services materially change

## MVP 7 Done Criteria

- [x] User can view books completed by month
- [x] User can view format breakdown
- [x] User can view top authors
- [x] User can view top genres
- [x] User can view books completed by selected period
- [x] User can view audiobook hours when known
- [x] User can view pages read when known
- [x] User can view partial-progress summaries
- [x] User can see re-read and re-listen counts derived from completed events
- [x] User can add prior read/listen entries for books consumed before tracking began
- [x] Lifetime enjoyed time is shown separately from current-loan progress
- [x] Libby `picked up` session count is not treated as true completed read/listen count
- [x] User can view series activity
- [x] User can generate a quarterly recap page
- [x] User can generate a yearly recap page
- [x] Recap shows favorite author, favorite genre, favorite series, longest book, most active month, and format mix
- [x] User can export a recap to Markdown or HTML
- [x] Analytics and recap generation preserve source data and manual edits
- [x] Basic tests pass
