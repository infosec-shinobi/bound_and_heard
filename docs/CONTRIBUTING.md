# Bound & Heard Contributing Guide

## Local Development Goals

This project should be easy to run locally.

The initial target environment is a single developer machine using:

- Python
- FastAPI
- SQLite
- Jinja2
- HTMX
- Bootstrap

## Prerequisites

Recommended:

- Python 3.12+
- Git
- uv or pip
- SQLite
- Playwright browsers, once scraping is added

## Suggested Setup

Clone the repo:

Windows PowerShell:

```powershell
git clone <repo-url>
cd bound-and-heard
```

Linux/macOS:

```bash
git clone <repo-url>
cd bound-and-heard
```

Create a virtual environment:

Windows PowerShell:

```powershell
python -m venv .venv
```

Linux/macOS:

```bash
python3 -m venv .venv
```

Activate it, if you prefer activated-shell commands:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Linux/macOS:

```bash
./.venv/bin/python -m pip install -e ".[dev]"
```

Use the project-local `.venv` for all Python commands. Do not install project dependencies into the global Python environment.

Install Playwright browser binaries when working on Libby progress scraping:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Linux/macOS:

```bash
./.venv/bin/python -m playwright install chromium
```

The Libby browser profile defaults to `data/browser/libby-profile`. It contains local cookies/session state, is covered by the existing `data/**` ignore rule, and should not be committed or used to store credentials in the database.

Configure write protection for local-network use:

Windows PowerShell:

```powershell
$env:BOUND_AND_HEARD_ADMIN_PASSWORD = "choose-a-local-admin-password"
```

Linux/macOS:

```bash
export BOUND_AND_HEARD_ADMIN_PASSWORD="choose-a-local-admin-password"
```

If `BOUND_AND_HEARD_ADMIN_PASSWORD` is not set, the app should start in read-only mode for safety. Read-only pages remain available, but mutating actions are disabled. The app should log a clear startup warning and the UI should explain disabled actions with a tooltip, popover, or inline message.

Optionally configure the default local user's display name before the first app startup:

Windows PowerShell:

```powershell
$env:BOUND_AND_HEARD_DEFAULT_USER_NAME = "Your Name"
```

Linux/macOS:

```bash
export BOUND_AND_HEARD_DEFAULT_USER_NAME="Your Name"
```

This value is used when the default local user is first created. It does not rename an existing user.

Run migrations after the database foundation has been implemented and Alembic has been initialized. This command will fail until `alembic.ini` and the Alembic migration environment exist.

After Alembic is set up, run migrations when setting up the app for the first time or after pulling changes that add new migration files. This does not need to be run before every app start if the database schema has not changed.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Linux/macOS:

```bash
./.venv/bin/python -m alembic upgrade head
```

Start the app:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Linux/macOS:

```bash
./.venv/bin/python -m uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000
```

## Development Philosophy

Prefer simple, boring code.

Avoid premature abstraction.

Build in MVP-sized increments.

## Code Organization

Use:

```text
api/        web routes
models/     SQLAlchemy models
schemas/    Pydantic schemas
services/   business logic
importers/  source-specific import code
scrapers/   automation code
templates/  Jinja templates
static/     CSS/JS/assets
tests/      automated tests
```

## Testing

Initial priorities:

- Libby JSON parser tests
- Book deduplication tests
- Import idempotency tests
- Progress skip logic tests
- Series ordering tests

Run tests:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Linux/macOS:

```bash
./.venv/bin/python -m pytest
```

## Data Safety

Do not commit personal Libby exports, scraped HTML, browser profiles, or SQLite databases.

Do not commit local passwords, session secrets, or `.env` files.

Recommended `.gitignore` entries:

```gitignore
# Keep data folder structure, ignore generated/imported data.
data/**
!data/
!data/**/
!data/**/.gitkeep

*.db
*.sqlite
*.sqlite3
.env
.venv/
__pycache__/
.pytest_cache/
data/browser/
```

## Documentation

Primary documentation lives in:

```text
docs/
├── ARCHITECTURE.md
├── ROADMAP.md
├── DATABASE.md
├── SCRAPING_STRATEGY.md
└── CONTRIBUTING.md
```

Update documentation when architectural decisions change.
