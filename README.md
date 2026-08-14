# Bound & Heard

Bound & Heard is a self-hosted, local-first reading and listening analytics app.

It is designed to track books read and listened to, import Libby timeline JSON, track series progress, analyze trends, generate quarterly/yearly recaps, and eventually provide AI-powered reading recommendations.

See the `docs/` folder for architecture and planning documents.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the app with development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Install Playwright browser binaries for Libby progress scraping:

```powershell
python -m playwright install chromium
```

Create a local `.env` file if you want write actions enabled:

```dotenv
BOUND_AND_HEARD_ADMIN_PASSWORD=change-me
BOUND_AND_HEARD_SESSION_SECRET=change-this-dev-secret
```

Run database migrations:

```powershell
alembic upgrade head
```

Start the app:

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Environment Variables

`BOUND_AND_HEARD_ADMIN_PASSWORD`

Shared local admin password. When missing or blank, read-only pages remain available and all write actions are disabled.

`BOUND_AND_HEARD_SESSION_SECRET`

Secret used to sign the browser session cookie. Set this locally before exposing the app beyond your own machine.

`BOUND_AND_HEARD_DATABASE_URL`

SQLAlchemy database URL. Defaults to `sqlite:///./data/bound_and_heard.sqlite3`.

`BOUND_AND_HEARD_DEFAULT_USER_NAME`

Display name used only when bootstrapping the first local user. It does not overwrite an existing user.

`BOUND_AND_HEARD_IMPORTS_DIR`

Directory used to preserve raw uploaded import files. Defaults to `data/imports`.

`BOUND_AND_HEARD_LIBBY_BROWSER_PROFILE_DIR`

Directory used for the persistent local Playwright browser profile for Libby. Defaults to `data/browser/libby-profile`. This directory contains local browser cookies/session state and should not be committed.

`BOUND_AND_HEARD_SCRAPED_DIR`

Directory used to preserve Libby scrape snapshots. Defaults to `data/scraped`. Snapshot files can contain private reading activity and should not be committed.

`BOUND_AND_HEARD_APP_NAME`

Application display name. Defaults to `Bound & Heard`.

## Libby JSON Imports

Libby timeline imports require write access.

1. Set `BOUND_AND_HEARD_ADMIN_PASSWORD` in `.env` and restart the app.
2. Open `/admin/login` and sign in with the admin password.
3. Open `/imports` from the navigation.
4. Upload a Libby timeline `.json` export.
5. Review the import summary page for checksum, row count, created/updated books, created events, skipped duplicate events, and raw file references.

Raw JSON uploads are preserved under `data/imports/libby/` by default. Exact duplicate files are detected by checksum and skipped without saving another raw copy or creating another import record.

Imported Libby books appear in `/books`, and imported reading events appear on each book detail page. Import updates fill empty metadata fields only; manual edits, notes, ratings, progress, completion dates, and manual correction events are preserved.

## Import Review Workflow

Open `/books/review` after importing Libby JSON to review imported records before relying on them for scraping, analytics, and recaps. The page remains readable without write access, but quick corrections require admin login.

Books need review when they are Libby-imported, not archived, and not marked reviewed or ignored. Filters help find missing or suspicious metadata, including missing page count, audio duration, author, publisher, ISBN, cover URL, unknown format/status, missing Libby title ID, fallback titles, missing reading events, completed books without completion dates, progress/status mismatches, and duplicate candidates.

Duplicate candidates are only flagged for same-format records. The review page flags matching Libby title ID and format, ISBN and format, or normalized title, author, and format. Audiobook, ebook, and physical records are kept separate unless they match within the same format. MVP 3 never auto-merges duplicates.

Admin users can make quick corrections from review rows:

- Status updates support want_to_read, borrowed, started, completed, abandoned, and unknown.
- Manual progress updates accept 0-100 percent, and blank clears manual progress.
- Completion date updates accept ISO dates, and blank clears the completion date.
- Archive, restore, reviewed, and ignored actions preserve the book record, reading events, progress rows, and import attribution.

Quick status, progress, and completion-date changes create `manually_corrected` reading events. Marking a book reviewed or ignored stores review state and a review note. Ignored and reviewed books stay out of the default review results.

## Libby Progress Scraping Setup

MVP 4 uses Playwright with a persistent local browser profile so you can log in to Libby manually and reuse that browser session for progress scraping. The default profile directory is `data/browser/libby-profile`, which is ignored by Git through the existing `data/**` rule.

Install the browser binary after installing dependencies:

```powershell
python -m playwright install chromium
```

Do not store Libby credentials in the app database or commit the browser profile directory. The profile contains local browser state such as cookies.

### Libby Progress Scraping Workflow

Libby progress scraping requires write access.

1. Set `BOUND_AND_HEARD_ADMIN_PASSWORD` in `.env`, restart the app, and log in at `/admin/login`.
2. Open `Libby Session` from the navigation and launch the persistent browser.
3. Log in to Libby manually in that browser window. Credentials and cookies stay in the local browser profile, not the app database.
4. Import Libby JSON and review imported books so scrape candidates have a Libby title ID and borrow event.
5. Open `Scrape Jobs` from the navigation, then create a new job.
6. Review queued, skipped, and ineligible books. Use force re-scrape if you intentionally want to ignore the last scraped borrow marker.
7. Start the job. The app opens Libby journey pages one at a time, waits between items, preserves raw snapshots, parses progress, and records per-item success or failure.

Scraping uses authenticated journey URLs like `https://libbyapp.com/shelf/journey/{libby_title_id}`. Public `share.libbyapp.com/title/...` pages are catalog pages and do not contain personal reading progress.

Books are skipped when their latest Libby borrow timestamp is less than or equal to `BookProgress.last_scraped_borrowed_at`. Force re-scrape bypasses that skip logic for a new job.

Failed items can be retried or skipped from the job detail page. Failed, cancelled, or completed jobs with open items can be recovered and restarted. Old jobs can be deleted from job history; deleting a job removes database job/item/snapshot records but does not delete snapshot files already written to disk.

Raw scrape snapshots are stored under `data/scraped/libby/job-{job_id}/item-{item_id}/` by default. These files may contain titles, library information, reading journey text, progress, and other private account state. Keep `data/**` untracked and avoid sharing snapshots unless you have reviewed them.

## Common Commands

Run the development server:

```powershell
uvicorn app.main:app --reload
```

Run migrations:

```powershell
alembic upgrade head
```

Create a migration after model changes:

```powershell
alembic revision --autogenerate -m "describe change"
```

Run tests:

```powershell
pytest
```

## Troubleshooting

If write buttons are disabled, set `BOUND_AND_HEARD_ADMIN_PASSWORD` in `.env`, restart the server, then log in at `/admin/login`.

If the app errors on missing tables, run `alembic upgrade head` from the project root.

If imports fail in tests, install the project in editable mode with `python -m pip install -e ".[dev]"`.

Local SQLite databases, imported data, exports, virtual environments, and `.env` files should stay untracked. Alembic migration files under `alembic/versions/` should be tracked.

## AI Usage

AI was leveraged in the creation and development of this application. It was expressed leveraged with my supervision and any code I did not write was reviewed by myself.
