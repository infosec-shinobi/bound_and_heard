# MVP 5 Checklist

## Goal

Track series manually first, including unread planned books, so the app can show where the user is in a series, what remains, what comes next, and whether the user plans to continue.

## Source

Derived from `docs/ROADMAP.md` MVP 5 - Series Tracking, with continuity from MVP 1 manual tracking, MVP 2 Libby imports, MVP 3 cleanup/review, and MVP 4 scraped progress.

## Chunk 1 - Series Data Model

- [ ] Decide table shape for `series` and `series_books`
- [ ] Add user-scoped `series` model with name, description, status, continuation intent, timestamps
- [ ] Add `series_books` model for existing-book assignments and planned/unowned entries
- [ ] Support series order/position with nullable numeric or text ordering where appropriate
- [ ] Support planned title/author/format fields for books not yet in the user's library
- [ ] Add indexes for user, status, series order, book lookup, and next-unread queries
- [ ] Add Alembic migration
- [ ] Verify `alembic upgrade head`

## Chunk 2 - Series List Page

- [ ] Add `/series` route and navigation entry
- [ ] List series with name, status, continuation intent, progress count, and next unread item
- [ ] Add filters for active, paused, completed, abandoned, unknown
- [ ] Add search by series name
- [ ] Show empty state with create action
- [ ] Keep read-only users able to view series
- [ ] Keep mutations protected by admin login

## Chunk 3 - Create And Edit Series

- [ ] Add protected create series form
- [ ] Add protected edit series form
- [ ] Validate required series name
- [ ] Support status values: active, paused, completed, abandoned, unknown
- [ ] Track whether the user wants to continue the series
- [ ] Preserve created_at and updated_at behavior
- [ ] Return clear success/error messages

## Chunk 4 - Series Detail Page

- [ ] Add series detail route
- [ ] Show name, description, status, continuation intent, and progress summary
- [ ] Show assigned existing books in series order
- [ ] Show planned/unowned books in series order
- [ ] Show book format, status, completion date, progress, and source context where useful
- [ ] Link existing books to book detail pages
- [ ] Highlight next unread book

## Chunk 5 - Assign Existing Books To Series

- [ ] Add protected action to assign an existing book to a series
- [ ] Search/select books by title, author, format, and source
- [ ] Prevent duplicate assignment of the same book to the same series
- [ ] Allow changing assigned book order/position
- [ ] Allow removing a book from a series without deleting the book
- [ ] Preserve book records, reading events, progress, and import attribution

## Chunk 6 - Planned Series Books

- [ ] Add protected action to create planned series entries without a local book record
- [ ] Store planned title, author, format, order/position, and notes if useful
- [ ] Allow editing planned entries
- [ ] Allow removing planned entries
- [ ] Allow converting a planned entry to an existing book assignment when the book is added/imported later
- [ ] Keep planned entries separate from real book records until explicitly linked

## Chunk 7 - Ordering And Position UX

- [ ] Define ordering semantics for whole numbers, decimals, novellas, prequels, and unknown order
- [ ] Sort series entries consistently by position then title
- [ ] Allow editing position inline or through forms
- [ ] Show unknown-position entries without breaking ordered entries
- [ ] Preserve order when adding or removing items

## Chunk 8 - Progress And Next-Unread Logic

- [ ] Define what counts as read/completed for existing books
- [ ] Define how planned/unowned entries affect remaining count
- [ ] Calculate completed count and total known/planned count
- [ ] Identify next unread item from ordered entries
- [ ] Handle abandoned, paused, and completed series status edge cases
- [ ] Avoid marking series complete automatically unless behavior is explicit and safe

## Chunk 9 - Series Status And Continuation Tracking

- [ ] Let user set status independent of book completion state
- [ ] Let user record wants-to-continue yes/no/unknown
- [ ] Surface abandoned or paused state clearly
- [ ] Surface series where next unread exists but user does not want to continue
- [ ] Preserve manual series state across imports and scraping

## Chunk 10 - Book Detail Integration

- [ ] Show series memberships on book detail pages
- [ ] Link from book detail to series detail
- [ ] Allow assigning/removing series membership from book detail if practical
- [ ] Avoid clutter when a book belongs to no series
- [ ] Support multiple series memberships only if needed and explicitly allowed

## Chunk 11 - Import/Review Integration

- [ ] Decide whether imported Libby metadata can suggest series candidates in MVP 5 or defer to enrichment
- [ ] Keep MVP 5 manual-first; do not auto-create series from imported text unless explicitly chosen
- [ ] Make it easy to assign reviewed/imported books to a series
- [ ] Preserve manual series assignments during later Libby imports
- [ ] Preserve manual series assignments during metadata enrichment in MVP 6

## Chunk 12 - Tests

- [ ] Test series model and migration fields
- [ ] Test series list and detail pages render expected state
- [ ] Test read-only users can view but cannot mutate series
- [ ] Test create/edit series validation and persistence
- [ ] Test assigning existing books to series
- [ ] Test duplicate assignment prevention
- [ ] Test planned book creation/edit/removal
- [ ] Test converting planned entry to existing book assignment if implemented
- [ ] Test ordering and next unread logic
- [ ] Test status and continuation intent display
- [ ] Test book detail series membership display
- [ ] Test imports/scrapes do not overwrite manual series state

## Chunk 13 - Documentation

- [ ] Update README with series tracking workflow
- [ ] Document manual-first series policy
- [ ] Document planned/unowned series entries
- [ ] Document ordering semantics and next-unread behavior
- [ ] Update database documentation for series tables and fields
- [ ] Note future metadata enrichment can suggest series but should not overwrite manual assignments

## MVP 5 Done Criteria

- [ ] User can create and edit series
- [ ] User can assign existing books to series
- [ ] User can add planned series books that are not yet in the library
- [ ] User can set series order/position
- [ ] User can track series status: active, paused, completed, abandoned, unknown
- [ ] User can track whether they want to continue a series
- [ ] Series detail shows completed/remaining progress
- [ ] Series detail shows the next unread book when available
- [ ] Series list shows completed, active, paused, and abandoned series states
- [ ] Manual series assignments survive imports and scraping
- [ ] Basic tests pass
