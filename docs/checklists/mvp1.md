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

- [x] Add `app/core/config.py`
- [x] Read settings from environment variables
- [x] Add `BOUND_AND_HEARD_ADMIN_PASSWORD`
- [x] Add app secret or session secret setting
- [x] Add database URL setting with SQLite default
- [x] Log startup warning when admin password is missing
- [x] Expose app-level `writes_enabled` state

## Chunk 3 - Database Foundation

- [x] Add `app/core/database.py`
- [x] Configure SQLAlchemy engine and session
- [x] Configure declarative base
- [x] Initialize Alembic
- [x] Wire Alembic to app models
- [x] Add first migration
- [x] Verify `alembic upgrade head`

## Chunk 4 - Core Models

- [x] Add `User` model
- [x] Add default local user bootstrap
- [x] Add `Book` model
- [x] Add `ReadingEvent` model
- [x] Add `BookProgress` model
- [x] Add timestamp fields
- [x] Add basic indexes
- [x] Add `user_id` to user-owned tables
- [x] Add `archived_at` to books for archive-only removal

## Chunk 5 - Write Protection

- [x] Add session middleware
- [x] Add admin login form/page
- [x] Verify admin password against `BOUND_AND_HEARD_ADMIN_PASSWORD`
- [x] Add logout action
- [x] Add dependency or helper for protected write actions
- [x] Disable mutating actions when env var is missing
- [x] Show tooltip, popover, or inline message for disabled actions
- [x] Keep read-only pages accessible

## Chunk 6 - Layout and Navigation

- [x] Add `base.html`
- [x] Add Bootstrap
- [x] Add navigation shell
- [x] Add home/dashboard page
- [x] Show current write-protection state in UI
- [x] Add reusable disabled-action UI pattern

## Chunk 7 - Book List

- [x] Add books route module
- [x] Add book list page
- [x] Show title, author, format, status, rating, and progress
- [x] Hide archived books by default
- [x] Add filter to include archived books
- [x] Add empty state
- [x] Add basic search/filter placeholders
- [x] Add protected Add Book action

## Chunk 8 - Add Book

- [x] Add new book form
- [x] Support title
- [x] Support subtitle
- [x] Support author name
- [x] Support format
- [x] Support status
- [x] Support rating
- [x] Support notes
- [x] Support started date
- [x] Support completed date
- [x] Support page count
- [x] Support audio duration
- [x] Support manual progress percent
- [x] Create initial reading events where appropriate
- [x] Redirect to detail page after create

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

## Future User Settings

- [ ] Add protected settings/profile page for updating the current user's display name
- [ ] Keep `BOUND_AND_HEARD_DEFAULT_USER_NAME` as first-run bootstrap only, not an overwrite mechanism
- [ ] Add dark/light mode toggle switch

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
