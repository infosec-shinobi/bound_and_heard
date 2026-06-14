# Bound & Heard Roadmap

## MVP 1 - Foundation, Manual Tracking, and Edit Protection

### Goals

Create a working FastAPI app with database persistence, manual book tracking, and safe write protection for local-network use.

### Deliverables

- FastAPI application skeleton
- SQLite database
- Alembic migrations
- Default local user
- User-owned tables with `user_id`
- Base layout with Bootstrap
- Admin-dashboard style navigation
- Env-var admin password using `BOUND_AND_HEARD_ADMIN_PASSWORD`
- Session-based protection for mutating actions
- Read-only mode when the admin password env var is missing
- Startup warning when writes are disabled because the env var is missing
- Tooltip, popover, or inline UI message explaining disabled write actions
- Book list page
- Book detail page
- Add book form
- Edit book form
- Delete or archive book action
- Manual format, status, progress, started date, completed date, rating, notes, page count, and audio duration fields
- Manual reading event creation for starts, completions, abandons, corrections, re-reads, and re-listens

### Success Criteria

The user can manually add, edit, view, and persist books. Write actions are protected when an admin password is configured and safely disabled when it is missing.

## MVP 2 - Libby JSON Import

### Goals

Import Libby timeline JSON exports and normalize the data into local tables without duplicating overlapping historical events.

### Deliverables

- Password-protected upload form for Libby JSON
- File checksum calculation
- Raw JSON preservation
- Duplicate file detection
- Event-level deduplication for overlapping exports
- Libby JSON parser
- Book creation/update logic
- Reading event creation
- Import summary page
- Manual overwrite protection

### Import Fields Observed

The current sample export includes:

- version
- timeline array
- cover metadata
- title metadata
- author
- publisher
- isbn
- timestamp
- activity
- details
- library metadata

### Success Criteria

The user uploads a Libby JSON export and books/events appear in the local database. Re-uploaded or overlapping exports do not create duplicate source events.

## MVP 3 - Import Review and Cleanup

### Goals

Provide a fast workflow for reviewing imported data before relying on it for scraping, analytics, and recaps.

### Deliverables

- Imported books needing review page
- Missing page count and audio duration filters
- Missing or ambiguous metadata filters
- Duplicate candidate review
- Quick status correction
- Quick progress correction
- Quick completion date correction
- Quick archive or ignore controls
- Manual correction events

### Success Criteria

The user can quickly clean up imported records and correct important fields without editing every book individually.

## MVP 4 - Libby Progress Scraping

### Goals

Use Playwright to retrieve progress data for imported Libby books, including partial progress where available.

### Deliverables

- Persistent browser profile
- Manual login flow
- Scrape job creation
- Per-book scrape job items
- Scrape queue
- 5-15 second randomized delay between pages
- Skip logic based on latest borrow timestamp
- Raw scrape snapshot preservation
- Progress parsing
- Partial progress capture
- Approximate completion date inference when exact completion date is unavailable
- Completion status update that respects manual corrections
- Failure capture per book
- Retry or skip failed scrape items

### Success Criteria

The app can update book progress without re-scraping unchanged books. A failed book does not fail the entire scrape job.

## MVP 5 - Series Tracking

### Goals

Track series manually first, including unread planned books, with enrichment later.

### Deliverables

- Create series
- Edit series
- Assign existing books to series
- Add planned series books that are not yet in the user's library
- Set series order/position
- Track status by series: active, paused, completed, abandoned, unknown
- Track whether the user wants to continue a series
- Show next unread book
- Show completed/active/paused/abandoned series

### Success Criteria

The user can determine where they are in a series, how many books remain, what book comes next, and whether they plan to continue.

## MVP 6 - Metadata Enrichment

### Goals

Enrich books with external metadata while caching all responses locally and protecting manual edits.

### Candidate Providers

- Open Library
- Google Books

### Deliverables

- ISBN lookup
- Title/author lookup fallback
- Cover image URL
- Page count
- Publication year
- Genre/category values
- Metadata cache
- Fill-empty-fields-only default behavior
- Manual overwrite protection
- Initial research into third-party series metadata providers

### Success Criteria

Books gain useful metadata without repeated API calls or silent overwrites of manual edits.

## MVP 7 - Analytics and Recaps

### Goals

Show trends in reading and listening behavior and generate fun recap pages.

### Deliverables

- Books by month
- Format breakdown
- Top authors
- Top genres
- Books completed by period
- Audiobook hours, when known
- Pages read, when known
- Partial progress summaries
- Re-read and re-listen counts derived from completed events
- Series activity
- Quarterly recap page
- Yearly recap page
- Favorite author
- Favorite genre
- Favorite series
- Longest book
- Most active month
- Format mix
- Export to Markdown or HTML

### Success Criteria

The user can understand what content they are consuming over time and generate personal reading/listening recaps.

## MVP 8 - Agentic Recommendations

### Goals

Add an explainable AI reading advisor.

### Deliverables

- Recommendation service interface
- Reading history summarizer
- Series continuation suggestions
- New series suggestions
- Genre exploration suggestions
- Explanation for each recommendation
- Optional local LLM integration

### Success Criteria

The app recommends useful next reads and explains why.

## Future Enhancements

- Multi-user login
- Per-user authentication and sessions
- Password-protected imports and edits per user
- Role-based access
- Public read-only recap links
- Docker deployment
- Postgres support
- Mobile-friendly recap pages
- Third-party series metadata enrichment
