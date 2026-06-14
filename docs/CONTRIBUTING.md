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

```bash
git clone <repo-url>
cd bound-and-heard
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -e ".[dev]"
```

Configure write protection for local-network use:

```powershell
$env:BOUND_AND_HEARD_ADMIN_PASSWORD = "choose-a-local-admin-password"
```

Linux/macOS:

```bash
export BOUND_AND_HEARD_ADMIN_PASSWORD="choose-a-local-admin-password"
```

If `BOUND_AND_HEARD_ADMIN_PASSWORD` is not set, the app should start in read-only mode for safety. Read-only pages remain available, but mutating actions are disabled. The app should log a clear startup warning and the UI should explain disabled actions with a tooltip, popover, or inline message.

Run migrations:

```bash
alembic upgrade head
```

Start the app:

```bash
uvicorn app.main:app --reload
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

```bash
pytest
```

## Data Safety

Do not commit personal Libby exports, scraped HTML, browser profiles, or SQLite databases.

Do not commit local passwords, session secrets, or `.env` files.

Recommended `.gitignore` entries:

```gitignore
data/
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
