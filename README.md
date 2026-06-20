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
