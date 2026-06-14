# Bound & Heard Database Design

## Design Goals

The database should be:

- Local-first
- Multi-user ready
- SQLite-compatible
- Postgres-compatible
- Friendly to imports, scraping, enrichment, and recaps
- Explicit about source attribution

## Core Rules

1. Every user-owned table gets `user_id`.
2. Raw source data is preserved.
3. Manual edits should not be silently overwritten.
4. Imports and scrapes should be resumable.
5. Data should support analytics without constant re-fetching.
6. Re-reads and re-listens should be represented as timestamped events, not only as counters.
7. Automated enrichment should fill empty fields only unless the user explicitly requests overwrite behavior.

## Entity Overview

```text
users
  |
  +-- books
  |     |
  |     +-- reading_events
  |     +-- book_progress
  |     +-- book_genres
  |     +-- series_books
  |
  +-- imports
  +-- jobs
  +-- recaps
  +-- recommendations
```

## Tables

### users

Stores application users.

MVP 1 creates one default local user. Full per-user authentication is deferred; write protection is handled by the shared admin password environment variable.

Fields:

- id
- display_name
- is_active
- created_at
- updated_at

Future authentication can add `email`, `password_hash`, and session-related fields.

### authors

Stores user-scoped author records.

Fields:

- id
- user_id
- name
- sort_name
- created_at
- updated_at

### books

Stores the user's local book records.

A book record represents a user-owned title in a specific consumed format. The same title may exist as separate audiobook, ebook, and physical records when those formats have different statistics, progress, identifiers, or metadata.

Fields:

- id
- user_id
- title
- subtitle
- author_id
- primary_author_name
- isbn10
- isbn13
- libby_title_id
- libby_share_url
- publisher
- format
- status
- rating
- notes
- started_on
- completed_on
- page_count
- audio_seconds
- manual_progress_percent
- cover_url
- cover_color
- title_source
- author_source
- metadata_source
- created_at
- updated_at

Recommended status values:

- want_to_read
- borrowed
- started
- completed
- abandoned
- unknown

Recommended format values:

- ebook
- audiobook
- physical
- unknown

### reading_events

Stores source events such as borrowed, returned, tagged, or manually completed.

This table is the source of truth for starts, completions, abandons, re-reads, and re-listens. Display values such as times completed should be derived from completed events.

Fields:

- id
- user_id
- book_id
- source
- source_event_id
- event_type
- event_date
- progress_percent
- raw_data
- created_at

Recommended event_type values:

- borrowed
- started
- progress_seen
- completed
- abandoned
- returned
- manually_completed
- manually_corrected

Observed Libby event fields:

- activity
- timestamp
- details
- library

### imports

Stores import-level metadata.

Fields:

- id
- user_id
- source
- filename
- checksum
- imported_at
- row_count
- status
- summary

### import_files

Stores raw file references.

Fields:

- id
- import_id
- file_path
- file_size
- content_type
- created_at

### book_progress

Stores the latest known progress for a book.

Fields:

- id
- user_id
- book_id
- source
- progress_percent
- position_seconds
- position_pages
- total_seconds
- total_pages
- last_borrowed_at
- last_scraped_borrowed_at
- observed_at
- scraped_at
- status_inferred
- created_at
- updated_at

### progress_snapshots

Stores references to raw scraped snapshots.

Fields:

- id
- user_id
- book_id
- book_progress_id
- source
- snapshot_path
- captured_at
- parser_version

### series

Stores user-created series records.

Fields:

- id
- user_id
- name
- description
- status
- created_at
- updated_at

Recommended status values:

- active
- paused
- completed
- abandoned
- unknown

### series_books

Maps books to series.

`book_id` is nullable so the app can represent planned or unread books in a series before those books exist in the user's library.

Fields:

- id
- user_id
- series_id
- book_id
- title
- author_name
- position
- position_label
- is_optional
- status
- notes
- created_at
- updated_at

### genres

Stores genre labels.

Fields:

- id
- user_id
- name
- source
- created_at

### book_genres

Maps books to genres.

Fields:

- id
- user_id
- book_id
- genre_id
- source
- created_at

### jobs

Stores work requests.

Examples:

- libby_import
- libby_progress_scrape
- metadata_enrichment
- recap_generation
- recommendation_generation

Fields:

- id
- user_id
- job_type
- status
- created_at
- started_at
- completed_at
- parameters
- summary

Recommended status values:

- pending
- running
- completed
- failed
- skipped
- cancelled

### job_runs

Stores job run details and logs.

Fields:

- id
- user_id
- job_id
- started_at
- completed_at
- status
- result
- logs

### job_items

Stores item-level work for resumable jobs, especially scrape jobs where one failed book should not fail the entire job.

Fields:

- id
- user_id
- job_id
- book_id
- status
- attempt_count
- last_error
- snapshot_path
- started_at
- completed_at

### metadata_cache

Caches external metadata responses.

Fields:

- id
- user_id
- provider
- lookup_key
- external_id
- payload
- cached_at
- expires_at

### recaps

Stores generated recap metadata.

Fields:

- id
- user_id
- period_type
- year
- quarter
- generated_at
- title
- summary
- output_path

Recommended period_type values:

- quarter
- year

### recommendations

Stores generated recommendations.

Fields:

- id
- user_id
- generated_at
- recommendation_type
- title
- author
- series_name
- reasoning
- source
- payload

## Deduplication Strategy

For Libby imports, prefer matching books by:

1. `libby_title_id`
2. `isbn13` or `isbn10`
3. normalized title + normalized author + format

A repeated borrow should create a new reading event, not necessarily a new book.

Whole-file checksums prevent reprocessing the exact same file, but they are not enough for repeated Libby exports with overlapping history. Reading events should also have a stable source identity, such as:

```text
source + libby_title_id + timestamp + activity + library_key + format
```

Use this value as `reading_events.source_event_id` or an equivalent unique constraint for source-event deduplication.

## Import Update Rules

When importing Libby JSON:

- Create missing books.
- Create reading events.
- Update Libby-specific fields.
- Do not overwrite manual notes, ratings, or manually edited fields.
- Fill empty metadata fields only unless the user explicitly requests overwrite behavior.
- If title/author changed from a source, preserve source attribution.

## Progress Skip Logic

A book does not need progress scraping if:

```text
latest_borrow_date <= last_scraped_borrowed_at
```

A book should be queued if:

```text
latest_borrow_date > last_scraped_borrowed_at
```

or if it has never been scraped.

## SQLite to Postgres Considerations

Avoid SQLite-only features when practical.

Use:

- integer primary keys
- ISO timestamps or timezone-aware datetime handling in application code
- JSON columns carefully through SQLAlchemy abstractions
