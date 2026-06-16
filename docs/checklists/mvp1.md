# MVP 1 Checklist

## Goal

Build the foundation for Bound & Heard: a local-first FastAPI app with manual book tracking, SQLite persistence, and safe write protection for local-network use.

## Chunk 1 - Project Foundation

- [x] Create Python package structure under `app/`
- [x] Add `pyproject.toml`
- [x] Configure dependencies: FastAPI, Uvicorn, SQLAlchemy 2.0, Alembic, Pydantic, pydantic-settings, Jinja2, python-multipart, pytest
- [x] Add `app/main.py`
- [x] Add basic health route
- [x] Add base app startup path
- [x] Verify app runs with `uvicorn app.main:app --reload`

## Chunk 2 - Configuration

- [ ] Add `app/core/config.py`
- [ ] Read settings from environment variables
- [ ] Add `BOUND_AND_HEARD_ADMIN_PASSWORD`
- [ ] Add app secret or session secret setting
- [ ] Add database URL setting with SQLite default
- [ ] Log startup warning when admin password is missing
- [ ] Expose app-level `writes_enabled` state

## Chunk 3 - Database Foundation

- [ ] Add `app/core/database.py`
- [ ] Configure SQLAlchemy engine and session
- [ ] Configure declarative base
- [ ] Initialize Alembic
- [ ] Wire Alembic to app models
- [ ] Add first migration
- [ ] Verify `alembic upgrade head`

## Chunk 4 - Core Models

- [ ] Add `User` model
- [ ] Add default local user bootstrap
- [ ] Add `Book` model
- [ ] Add `ReadingEvent` model
- [ ] Add `BookProgress` model
- [ ] Add timestamp fields
- [ ] Add basic indexes
- [ ] Add `user_id` to user-owned tables
- [ ] Add `archived_at` to books for archive-only removal

## Chunk 5 - Write Protection

- [ ] Add session middleware
- [ ] Add admin login form/page
- [ ] Verify admin password against `BOUND_AND_HEARD_ADMIN_PASSWORD`
- [ ] Add logout action
- [ ] Add dependency or helper for protected write actions
- [ ] Disable mutating actions when env var is missing
- [ ] Show tooltip, popover, or inline message for disabled actions
- [ ] Keep read-only pages accessible

## Chunk 6 - Layout and Navigation

- [ ] Add `base.html`
- [ ] Add Bootstrap
- [ ] Add navigation shell
- [ ] Add home/dashboard page
- [ ] Show current write-protection state in UI
- [ ] Add reusable disabled-action UI pattern

## Chunk 7 - Book List

- [ ] Add books route module
- [ ] Add book list page
- [ ] Show title, author, format, status, rating, and progress
- [ ] Hide archived books by default
- [ ] Add filter to include archived books
- [ ] Add empty state
- [ ] Add basic search/filter placeholders
- [ ] Add protected Add Book action

## Chunk 8 - Add Book

- [ ] Add new book form
- [ ] Support title
- [ ] Support subtitle
- [ ] Support author name
- [ ] Support format
- [ ] Support status
- [ ] Support rating
- [ ] Support notes
- [ ] Support started date
- [ ] Support completed date
- [ ] Support page count
- [ ] Support audio duration
- [ ] Support manual progress percent
- [ ] Create initial reading events where appropriate
- [ ] Redirect to detail page after create

## Chunk 9 - Book Detail

- [ ] Add book detail page
- [ ] Show core metadata
- [ ] Show progress
- [ ] Show page/audio stats
- [ ] Show reading event history
- [ ] Add protected Edit action
- [ ] Add protected Archive action
- [ ] Show archived state when applicable

## Chunk 10 - Edit Book

- [ ] Add edit form
- [ ] Update book fields
- [ ] Create correction event when status, progress, or completion changes
- [ ] Avoid silently deleting event history
- [ ] Redirect to detail page after save

## Chunk 11 - Archive Book

- [ ] Implement archive instead of hard delete
- [ ] Set `archived_at` when a book is archived
- [ ] Hide archived books from the default list
- [ ] Allow viewing archived books with a filter
- [ ] Add restore action if it remains simple
- [ ] Preserve reading events, progress, notes, ratings, and Libby identifiers

## Chunk 12 - Tests

- [ ] Test settings behavior when admin password is missing
- [ ] Test write protection blocks mutating actions
- [ ] Test read-only pages still work
- [ ] Test default user bootstrap
- [ ] Test manual book creation
- [ ] Test reading event creation
- [ ] Test progress field validation
- [ ] Test archive behavior

## Chunk 13 - Developer Experience

- [ ] Update README with setup instructions
- [ ] Document env vars
- [ ] Document run command
- [ ] Document migration command
- [ ] Document test command
- [ ] Confirm `.gitignore` excludes local data and secrets

## MVP 1 Done Criteria

- [ ] App starts locally
- [ ] SQLite database persists data
- [ ] Migrations run cleanly
- [ ] Default local user exists
- [ ] Missing admin password logs a warning
- [ ] Missing admin password disables write actions
- [ ] Configured admin password allows protected writes after login
- [ ] User can manually add a book
- [ ] User can edit a book
- [ ] User can view book details
- [ ] User can archive a book safely
- [ ] Archived books are hidden by default but can be viewed with a filter
- [ ] Manual status, progress, and completion changes create reading events
- [ ] Basic tests pass
