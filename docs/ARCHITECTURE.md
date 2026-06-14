# Bound & Heard Architecture

## Overview

Bound & Heard is a self-hosted, local-first reading and listening analytics platform.

The product provides a single place to:

- Track books read and listened to
- Import Libby timeline history from JSON exports
- Track progress through series
- Analyze reading/listening trends
- Generate quarterly and yearly recap reports
- Eventually provide AI-assisted recommendations

The project should favor boring, maintainable architecture over novelty. The goal is a tool that can be understood and maintained months later with limited spare time.

## Product Goals

### Library Management

Bound & Heard should allow the user to:

- Add books manually
- Import books from Libby JSON exports
- Edit book metadata
- Track format: ebook, audiobook, physical, unknown
- Track status: want to read, borrowed, started, completed, abandoned, unknown
- Track manual progress, start dates, completion dates, page counts, and audio duration
- Maintain notes and ratings

Book records are format-specific user records. If the same title is consumed as an audiobook and an ebook, those can be separate records because they have different progress, statistics, identifiers, and metadata.

### Libby Import

The first automated source is the Libby Timeline JSON export.

The initial sample export has this shape:

```json
{
  "version": 1,
  "timeline": [
    {
      "cover": {
        "contentType": "image/jpeg",
        "url": "...",
        "title": "...",
        "color": "#...",
        "format": "audiobook"
      },
      "title": {
        "text": "...",
        "url": "https://share.libbyapp.com/title/...",
        "titleId": "..."
      },
      "author": "...",
      "publisher": "...",
      "isbn": "...",
      "timestamp": 1767903363000,
      "activity": "Borrowed",
      "details": " 21 days ",
      "library": {
        "text": "...",
        "url": "...",
        "key": "..."
      }
    }
  ]
}
```

The importer should preserve the raw JSON, calculate a checksum, prevent duplicate import processing, and normalize data into internal tables.

Import idempotency should not rely only on whole-file checksums. Libby exports may overlap across repeated exports, so individual source events should also be deduplicated by stable source fields such as title ID, timestamp, activity, library key, and format.

### Series Tracking

Bound & Heard should answer:

- What series have I started?
- What books remain in each series?
- What book is next?
- Which series are complete?
- Which series appear abandoned?

Series tracking should be manual-first with metadata enrichment later.

Series should support planned or unread entries before those books exist in the user's library. This allows a series page to show, for example, 4 of 8 books completed and identify the next unread book.

### Analytics

The application should show trends across:

- Time period
- Format
- Author
- Genre
- Series
- Completion status
- Library source

### Recaps

Bound & Heard should generate fun recap pages:

- Quarterly recap
- Yearly recap
- Favorite author
- Favorite genre
- Most consumed format
- Most active month
- Books completed
- Audiobook hours
- Pages read
- Series progress
- Suggested next reads

### Agentic Recommendations

A future recommendation agent should review the user's reading/listening history and suggest new content.

Recommendations should be explainable.

Example:

> Because you completed several military sci-fi and progression fantasy audiobooks quickly, you may enjoy The Murderbot Diaries, Red Rising, or The Black Ocean series.

## Non-Goals

The initial product will not:

- Replace Libby
- Sync progress back to Libby
- Be a public social platform
- Require cloud hosting
- Require external AI services
- Require multi-user login in MVP 1

## Technology Stack

### Backend

- FastAPI
- SQLAlchemy 2.0
- Alembic
- Pydantic

### Edit Protection

MVP 1 should protect mutating actions with a simple admin password configured by environment variable.

Suggested variable:

```text
BOUND_AND_HEARD_ADMIN_PASSWORD
```

Read-only pages may remain accessible on the local network, but write actions require an authenticated session. If the password variable is missing, the application starts in read-only mode for safety: mutating actions are disabled, a clear startup warning is logged, and the UI should explain disabled actions with a tooltip, popover, or inline message.

Protected actions include:

- Add, edit, delete, or archive books
- Import Libby JSON
- Start scrape jobs
- Edit series
- Run metadata enrichment
- Generate or overwrite recaps
- Update user-owned settings

### Frontend

- Jinja2
- HTMX
- Bootstrap

### Database

- SQLite for MVP
- Postgres-compatible schema for future migration

### Automation

- Playwright for Libby progress scraping

### Future AI

- Local LLM through Ollama or OpenAI-compatible APIs
- Agentic recommendation service

## UI Philosophy

The main app should begin as an admin-dashboard style interface:

- Searchable tables
- Filters
- Edit forms
- Import status
- Job status

Inspired by:

- Paperless-ngx
- Immich
- Plex Admin
- Komodo

More visual, consumer-style pages should be added selectively:

- Book detail pages
- Series detail pages
- Quarterly recaps
- Yearly recaps
- Recommendation pages

## High-Level Architecture

```text
Browser
  |
  v
FastAPI application
  |
  +-- Web routes
  +-- HTMX partial routes
  +-- Service layer
        |
        +-- Import service
        +-- Scraping service
        +-- Metadata service
        +-- Series service
        +-- Analytics service
        +-- Recap service
        +-- Recommendation service
  |
  v
SQLAlchemy models
  |
  v
SQLite database
```

## Project Structure

```text
bound-and-heard/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── books.py
│   │   ├── imports.py
│   │   ├── series.py
│   │   ├── recaps.py
│   │   └── scrape.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   └── security.py
│   ├── models/
│   │   ├── user.py
│   │   ├── book.py
│   │   ├── author.py
│   │   ├── series.py
│   │   ├── import_record.py
│   │   ├── reading_event.py
│   │   ├── progress.py
│   │   └── job.py
│   ├── schemas/
│   ├── services/
│   │   ├── import_service.py
│   │   ├── metadata_service.py
│   │   ├── series_service.py
│   │   ├── analytics_service.py
│   │   ├── recap_service.py
│   │   └── recommendation_service.py
│   ├── importers/
│   │   └── libby_json.py
│   ├── scrapers/
│   │   └── libby_progress.py
│   ├── templates/
│   └── static/
├── alembic/
├── data/
│   ├── imports/
│   ├── scraped/
│   ├── enriched/
│   └── exports/
├── docs/
├── tests/
├── pyproject.toml
└── README.md
```

## Data Preservation Philosophy

Never throw away source data.

Bound & Heard should preserve:

- Original Libby JSON imports
- Raw scraped HTML or JSON
- Metadata API responses
- Generated recap exports

Suggested local data layout:

```text
data/
├── imports/
│   └── libby/
├── scraped/
│   └── libby/
├── enriched/
│   ├── openlibrary/
│   └── googlebooks/
└── exports/
    └── recaps/
```

This makes future reprocessing possible without repeated scraping or API calls.

## Multi-User Strategy

MVP 1 is single-user, but the schema should support future multi-user behavior.

Every user-owned table includes:

```text
user_id
```

A default local user is created automatically during setup.

Future authentication can add:

- Login screen
- Password hash
- Sessions
- Per-user imports
- Per-user libraries
- Edit/import route protection

Until full authentication exists, the app uses a default local user and a shared admin password for write protection. User-owned records should still include `user_id` so a future version can keep each user's library, imports, progress, series, recaps, and recommendations separate.

## Source Attribution

Metadata should track its source whenever practical.

Possible sources:

- manual
- libby
- scraped
- openlibrary
- googlebooks
- agent

Manual user edits should win over automated enrichment unless the user explicitly requests overwrite behavior.

For MVP behavior, automated enrichment should fill empty fields only unless the field is source-owned or the user explicitly requests an overwrite. Re-reads and re-listens should be represented as timestamped reading events rather than only as a counter on the book record.
