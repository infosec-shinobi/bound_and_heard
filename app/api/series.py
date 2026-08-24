from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request, status as http_status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import Book, LibbySeriesSnapshot, Series, SeriesBook
from app.services import libby_scrape_runner
from app.services.libby_series import (
    apply_libby_series_population,
    build_libby_series_population_preview,
    latest_libby_series_snapshot,
    read_libby_series_snapshot_content,
    suggested_libby_series_url,
)


router = APIRouter(prefix="/series", tags=["series"])

SERIES_STATUSES = ["active", "paused", "completed", "abandoned", "unknown"]
CONTINUATION_INTENTS = ["yes", "no", "unknown"]
SERIES_BOOK_FORMATS = ["ebook", "audiobook", "physical", "unknown"]
SERIES_ORDERING_HELP = (
    "Use whole numbers for main books, decimals for novellas or side stories, "
    "negative numbers for prequels, and leave blank when order is unknown. "
    "Unknown-position entries appear after numbered entries, sorted by title."
)


@dataclass(frozen=True)
class SeriesListItem:
    series: Series
    completed_count: int
    total_count: int
    next_unread_title: str | None
    next_unread_author: str | None
    continuation_notice: str | None


@dataclass(frozen=True)
class SeriesDetailEntry:
    entry: SeriesBook
    title: str
    author: str | None
    entry_type: str
    book_format: str | None
    status: str
    completed_on: date | None
    progress_percent: float | None
    source: str | None
    is_completed: bool
    is_next_unread: bool
    is_collection: bool
    is_covered_by_collection: bool


def is_series_entry_completed(entry: SeriesBook) -> bool:
    if entry.book is None:
        return False
    if entry.book.status == "completed":
        return True
    return bool(entry.book.progress and entry.book.progress.progress_percent == 100)


def is_collection_entry(entry: SeriesBook) -> bool:
    return entry.position is not None and entry.position_end is not None and entry.position_end > entry.position


def collection_covers_position(entry: SeriesBook, position: float | None) -> bool:
    if position is None or not is_collection_entry(entry):
        return False
    return bool(entry.position is not None and entry.position <= position <= entry.position_end)


def countable_series_entries(entries: list[SeriesBook]) -> list[SeriesBook]:
    non_collection_entries = [entry for entry in entries if not is_collection_entry(entry)]
    return non_collection_entries or entries


def completed_collection_entries(entries: list[SeriesBook]) -> list[SeriesBook]:
    return [entry for entry in entries if is_collection_entry(entry) and is_series_entry_completed(entry)]


def is_entry_satisfied(entry: SeriesBook, completed_collections: list[SeriesBook]) -> bool:
    return is_series_entry_completed(entry) or any(
        collection_covers_position(collection, entry.position) for collection in completed_collections
    )


def series_entry_title(entry: SeriesBook) -> str:
    if entry.book is not None:
        return entry.book.title
    return entry.planned_title or "Untitled planned book"


def series_entry_author(entry: SeriesBook) -> str | None:
    if entry.book is not None:
        return entry.book.primary_author_name
    return entry.planned_author_name


def series_entry_format(entry: SeriesBook) -> str | None:
    if entry.book is not None:
        return entry.book.format
    return entry.planned_format


def series_entry_progress(entry: SeriesBook) -> float | None:
    if entry.book is None:
        return None
    if entry.book.progress and entry.book.progress.progress_percent is not None:
        return entry.book.progress.progress_percent
    return entry.book.manual_progress_percent


def series_entry_source(entry: SeriesBook) -> str | None:
    if entry.book is None:
        return "planned"
    return entry.book.metadata_source


def series_entry_sort_key(entry: SeriesBook) -> tuple[int, float, str]:
    if entry.position is None:
        return (1, 0, series_entry_title(entry).casefold())
    return (0, entry.position, series_entry_title(entry).casefold())


def build_series_list_item(series: Series) -> SeriesListItem:
    entries = sorted(series.books, key=series_entry_sort_key)
    completed_collections = completed_collection_entries(entries)
    countable_entries = countable_series_entries(entries)
    completed_count = sum(1 for entry in countable_entries if is_entry_satisfied(entry, completed_collections))
    next_unread = next((entry for entry in countable_entries if not is_entry_satisfied(entry, completed_collections)), None)

    return SeriesListItem(
        series=series,
        completed_count=completed_count,
        total_count=len(countable_entries),
        next_unread_title=series_entry_title(next_unread) if next_unread else None,
        next_unread_author=series_entry_author(next_unread) if next_unread else None,
        continuation_notice=series_continuation_notice(series, series_entry_title(next_unread) if next_unread else None),
    )


def build_series_detail_entries(series: Series) -> list[SeriesDetailEntry]:
    entries = sorted(series.books, key=series_entry_sort_key)
    completed_collections = completed_collection_entries(entries)
    countable_entries = countable_series_entries(entries)
    next_unread = next((entry for entry in countable_entries if not is_entry_satisfied(entry, completed_collections)), None)
    detail_entries: list[SeriesDetailEntry] = []

    for entry in entries:
        is_planned = entry.book is None
        covered_by_collection = any(collection_covers_position(collection, entry.position) for collection in completed_collections)
        detail_entries.append(
            SeriesDetailEntry(
                entry=entry,
                title=series_entry_title(entry),
                author=series_entry_author(entry),
                entry_type="planned" if is_planned else "owned",
                book_format=series_entry_format(entry),
                status="planned" if is_planned else entry.book.status,
                completed_on=None if is_planned else entry.book.completed_on,
                progress_percent=series_entry_progress(entry),
                source=series_entry_source(entry),
                is_completed=is_series_entry_completed(entry) or covered_by_collection,
                is_next_unread=entry is next_unread,
                is_collection=is_collection_entry(entry),
                is_covered_by_collection=covered_by_collection and not is_collection_entry(entry),
            )
        )

    return detail_entries


def series_progress_note(series: Series, completed_count: int, total_count: int, next_unread: SeriesDetailEntry | None) -> str:
    remaining_count = total_count - completed_count
    if total_count == 0:
        return "No books or planned entries are tracked yet."
    if next_unread is None:
        return "All tracked entries are complete or read. Series status remains manual."
    if series.status == "completed":
        return f"Series is marked Completed, but {remaining_count} tracked entries remain unread or planned."
    if series.status == "paused":
        return f"Series is paused. Next unread remains {next_unread.title}."
    if series.status == "abandoned":
        return f"Series is abandoned. Next unread remains {next_unread.title} if you resume."
    return f"{remaining_count} tracked entries remain unread or planned."


def series_continuation_notice(series: Series, next_unread_title: str | None) -> str | None:
    if series.wants_to_continue == "no" and next_unread_title is not None:
        return f"Marked not continuing; next unread is {next_unread_title}."
    if series.wants_to_continue == "unknown" and next_unread_title is not None:
        return "Continuation intent is unknown."
    return None


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def submitted_series_form(
    *,
    name: str | None,
    description: str | None,
    status: str,
    wants_to_continue: str,
) -> dict[str, str]:
    return {
        "name": name or "",
        "description": description or "",
        "status": status,
        "wants_to_continue": wants_to_continue,
    }


def series_form_values(series: Series) -> dict[str, str]:
    return {
        "name": series.name,
        "description": series.description or "",
        "status": series.status,
        "wants_to_continue": series.wants_to_continue,
    }


def validate_series_form(name: str | None, status: str, wants_to_continue: str) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    clean_name = clean_optional(name)
    if clean_name is None:
        errors.append("Series name is required.")
    if status not in SERIES_STATUSES:
        errors.append("Status is invalid.")
    if wants_to_continue not in CONTINUATION_INTENTS:
        errors.append("Continuation intent is invalid.")
    return clean_name, errors


def parse_optional_position(value: str | None, errors: list[str]) -> float | None:
    value = clean_optional(value)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        errors.append("Position must be a number.")
        return None


def validate_planned_entry_form(
    title: str | None,
    planned_format: str,
    position: str | None,
) -> tuple[str | None, float | None, list[str]]:
    errors: list[str] = []
    clean_title = clean_optional(title)
    if clean_title is None:
        errors.append("Planned title is required.")
    if planned_format not in SERIES_BOOK_FORMATS:
        errors.append("Format is invalid.")
    parsed_position = parse_optional_position(position, errors)
    return clean_title, parsed_position, errors


def series_redirect(**params: str) -> RedirectResponse:
    return RedirectResponse(
        f"/series?{urlencode(params)}",
        status_code=http_status.HTTP_303_SEE_OTHER,
    )


def series_detail_redirect(series_id: int, **params: str) -> RedirectResponse:
    query = urlencode(params)
    target = f"/series/{series_id}"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target, status_code=http_status.HTTP_303_SEE_OTHER)


def get_local_series_statement(series_id: int):
    return (
        select(Series)
        .options(
            joinedload(Series.books).joinedload(SeriesBook.book).joinedload(Book.progress),
            joinedload(Series.books).joinedload(SeriesBook.book).joinedload(Book.libby_series_hints),
            joinedload(Series.libby_snapshots),
        )
        .where(Series.id == series_id, Series.user_id == DEFAULT_LOCAL_USER_ID)
    )


def book_option_label(book: Book) -> str:
    parts = [book.title]
    if book.primary_author_name:
        parts.append(book.primary_author_name)
    parts.append(book.format.replace("_", " ").title())
    parts.append((book.metadata_source or "missing source").replace("_", " ").title())
    return " - ".join(parts)


def get_local_series(db: Session, series_id: int) -> Series | None:
    series = db.get(Series, series_id)
    if series is None or series.user_id != DEFAULT_LOCAL_USER_ID:
        return None
    return series


def get_series_entry(db: Session, series: Series, entry_id: int) -> SeriesBook | None:
    entry = db.get(SeriesBook, entry_id)
    if entry is None or entry.series_id != series.id:
        return None
    return entry


def selectable_books_statement(book_q: str | None):
    statement = select(Book).where(Book.user_id == DEFAULT_LOCAL_USER_ID).order_by(Book.title.asc())
    if book_q:
        search = f"%{book_q.strip()}%"
        statement = statement.where(
            or_(
                Book.title.ilike(search),
                Book.primary_author_name.ilike(search),
                Book.format.ilike(search),
                Book.metadata_source.ilike(search),
            )
        )
    return statement


def relative_age_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = max(0, int((now - value).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def render_series_detail_view(
    *,
    request: Request,
    db: Session,
    series: Series,
    book_q: str | None,
    message: str | None,
    error: str | None,
    libby_series_preview: object | None = None,
    libby_series_page_content: str = "",
    libby_include_unmatched: bool = False,
    libby_series_snapshot_id: int | None = None,
) -> HTMLResponse:
    entries = build_series_detail_entries(series)
    countable_entries = [entry for entry in entries if not entry.is_collection] or entries
    completed_count = sum(1 for entry in countable_entries if entry.is_completed)
    next_unread = next((entry for entry in entries if entry.is_next_unread), None)
    progress_note = series_progress_note(series, completed_count, len(countable_entries), next_unread)
    continuation_notice = series_continuation_notice(series, next_unread.title if next_unread else None)
    selectable_books = db.scalars(selectable_books_statement(book_q)).all()
    latest_snapshot = latest_libby_series_snapshot(db, series_id=series.id, user_id=DEFAULT_LOCAL_USER_ID)

    return templates.TemplateResponse(
        request,
        "series/detail.html",
        template_context(
            request,
            page_title=series.name,
            series=series,
            entries=entries,
            completed_count=completed_count,
            total_count=len(countable_entries),
            next_unread=next_unread,
            remaining_count=len(countable_entries) - completed_count,
            progress_note=progress_note,
            continuation_notice=continuation_notice,
            selectable_books=selectable_books,
            book_options={book.id: book_option_label(book) for book in selectable_books},
            book_q=book_q or "",
            series_book_formats=SERIES_BOOK_FORMATS,
            ordering_help=SERIES_ORDERING_HELP,
            message=message,
            error=error,
            libby_series_preview=libby_series_preview,
            libby_series_page_content=libby_series_page_content,
            libby_include_unmatched=libby_include_unmatched,
            libby_series_snapshot_id=libby_series_snapshot_id,
            latest_libby_series_snapshot=latest_snapshot,
            latest_libby_series_snapshot_age=relative_age_text(latest_snapshot.created_at if latest_snapshot else None),
            suggested_libby_series_url=suggested_libby_series_url(db, series=series) or "",
        ),
    )


@router.get("", response_class=HTMLResponse)
async def series_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    statement = (
        select(Series)
        .options(
            joinedload(Series.books).joinedload(SeriesBook.book).joinedload(Book.progress),
        )
        .where(Series.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(Series.name.asc())
    )

    if q:
        search = f"%{q.strip()}%"
        statement = statement.where(Series.name.ilike(search))

    if status in SERIES_STATUSES:
        statement = statement.where(Series.status == status)

    series_items = [build_series_list_item(series) for series in db.scalars(statement).unique().all()]
    status_counts = dict.fromkeys(SERIES_STATUSES, 0)
    count_statement = select(Series.status).where(Series.user_id == DEFAULT_LOCAL_USER_ID)
    for series_status in db.scalars(count_statement):
        if series_status in status_counts:
            status_counts[series_status] += 1

    return templates.TemplateResponse(
        request,
        "series/list.html",
        template_context(
            request,
            page_title="Series",
            series_items=series_items,
            q=q or "",
            selected_status=status or "",
            series_statuses=SERIES_STATUSES,
            status_counts=status_counts,
            message=message,
            error=error,
        ),
    )


@router.get("/new", response_class=HTMLResponse)
async def new_series_form(
    request: Request,
    _: None = Depends(require_write_access),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "series/form.html",
        template_context(
            request,
            page_title="Create Series",
            heading="Create Series",
            description="Start a manually tracked series. Books and planned entries come next.",
            form_action="/series/new",
            cancel_href="/series",
            submit_label="Create Series",
            errors=[],
            form={"status": "unknown", "wants_to_continue": "unknown"},
            series_statuses=SERIES_STATUSES,
            continuation_intents=CONTINUATION_INTENTS,
        ),
    )


@router.post("/new")
async def create_series(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    name: str = Form(default=""),
    description: str | None = Form(default=None),
    status: str = Form(default="unknown"),
    wants_to_continue: str = Form(default="unknown"),
) -> Response:
    form = submitted_series_form(
        name=name,
        description=description,
        status=status,
        wants_to_continue=wants_to_continue,
    )
    clean_name, errors = validate_series_form(name, status, wants_to_continue)

    if errors:
        return templates.TemplateResponse(
            request,
            "series/form.html",
            template_context(
                request,
                page_title="Create Series",
                heading="Create Series",
                description="Start a manually tracked series. Books and planned entries come next.",
                form_action="/series/new",
                cancel_href="/series",
                submit_label="Create Series",
                errors=errors,
                form=form,
                series_statuses=SERIES_STATUSES,
                continuation_intents=CONTINUATION_INTENTS,
            ),
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )

    series = Series(
        user_id=DEFAULT_LOCAL_USER_ID,
        name=clean_name or "",
        description=clean_optional(description),
        status=status,
        wants_to_continue=wants_to_continue,
    )
    db.add(series)
    db.commit()
    return series_redirect(message=f"Series created: {series.name}")


@router.get("/{series_id}/edit", response_class=HTMLResponse)
async def edit_series_form(
    series_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> Response:
    series = db.get(Series, series_id)
    if series is None or series.user_id != DEFAULT_LOCAL_USER_ID:
        return series_redirect(error="Series not found.")

    return templates.TemplateResponse(
        request,
        "series/form.html",
        template_context(
            request,
            page_title="Edit Series",
            heading="Edit Series",
            description="Update manual series status and continuation intent.",
            form_action=f"/series/{series.id}/edit",
            cancel_href="/series",
            submit_label="Save Changes",
            errors=[],
            form=series_form_values(series),
            series_statuses=SERIES_STATUSES,
            continuation_intents=CONTINUATION_INTENTS,
        ),
    )


@router.post("/{series_id}/edit")
async def update_series(
    series_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    name: str = Form(default=""),
    description: str | None = Form(default=None),
    status: str = Form(default="unknown"),
    wants_to_continue: str = Form(default="unknown"),
) -> Response:
    series = db.get(Series, series_id)
    if series is None or series.user_id != DEFAULT_LOCAL_USER_ID:
        return series_redirect(error="Series not found.")

    form = submitted_series_form(
        name=name,
        description=description,
        status=status,
        wants_to_continue=wants_to_continue,
    )
    clean_name, errors = validate_series_form(name, status, wants_to_continue)

    if errors:
        return templates.TemplateResponse(
            request,
            "series/form.html",
            template_context(
                request,
                page_title="Edit Series",
                heading="Edit Series",
                description="Update manual series status and continuation intent.",
                form_action=f"/series/{series.id}/edit",
                cancel_href="/series",
                submit_label="Save Changes",
                errors=errors,
                form=form,
                series_statuses=SERIES_STATUSES,
                continuation_intents=CONTINUATION_INTENTS,
            ),
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )

    series.name = clean_name or ""
    series.description = clean_optional(description)
    series.status = status
    series.wants_to_continue = wants_to_continue
    db.commit()
    return series_redirect(message=f"Series updated: {series.name}")


@router.post("/{series_id}/books/add")
async def add_existing_book_to_series(
    series_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    book_id: int = Form(...),
    position: str | None = Form(default=None),
) -> Response:
    series = db.get(Series, series_id)
    if series is None or series.user_id != DEFAULT_LOCAL_USER_ID:
        return series_redirect(error="Series not found.")

    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return series_detail_redirect(series.id, error="Book not found.")

    existing = db.scalars(
        select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.book_id == book.id)
    ).first()
    if existing is not None:
        return series_detail_redirect(series.id, error=f"{book.title} is already in this series.")

    errors: list[str] = []
    parsed_position = parse_optional_position(position, errors)
    if errors:
        return series_detail_redirect(series.id, error=errors[0])

    db.add(SeriesBook(series_id=series.id, book_id=book.id, position=parsed_position))
    db.commit()
    return series_detail_redirect(series.id, message=f"Added {book.title} to this series.")


@router.post("/{series_id}/entries/{entry_id}/position")
async def update_series_entry_position(
    series_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    position: str | None = Form(default=None),
) -> Response:
    series = db.get(Series, series_id)
    if series is None or series.user_id != DEFAULT_LOCAL_USER_ID:
        return series_redirect(error="Series not found.")

    entry = db.get(SeriesBook, entry_id)
    if entry is None or entry.series_id != series.id or entry.book_id is None:
        return series_detail_redirect(series.id, error="Series book entry not found.")

    errors: list[str] = []
    parsed_position = parse_optional_position(position, errors)
    if errors:
        return series_detail_redirect(series.id, error=errors[0])

    entry.position = parsed_position
    db.commit()
    return series_detail_redirect(series.id, message="Series position updated.")


@router.post("/{series_id}/entries/{entry_id}/remove")
async def remove_existing_book_from_series(
    series_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> Response:
    series = db.get(Series, series_id)
    if series is None or series.user_id != DEFAULT_LOCAL_USER_ID:
        return series_redirect(error="Series not found.")

    entry = db.get(SeriesBook, entry_id)
    if entry is None or entry.series_id != series.id or entry.book_id is None:
        return series_detail_redirect(series.id, error="Series book entry not found.")

    db.delete(entry)
    db.commit()
    return series_detail_redirect(series.id, message="Removed book from this series.")


@router.post("/{series_id}/planned/add")
async def add_planned_series_entry(
    series_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    planned_title: str = Form(default=""),
    planned_author_name: str | None = Form(default=None),
    planned_format: str = Form(default="unknown"),
    position: str | None = Form(default=None),
    notes: str | None = Form(default=None),
) -> Response:
    series = get_local_series(db, series_id)
    if series is None:
        return series_redirect(error="Series not found.")

    clean_title, parsed_position, errors = validate_planned_entry_form(planned_title, planned_format, position)
    if errors:
        return series_detail_redirect(series.id, error=errors[0])

    db.add(
        SeriesBook(
            series_id=series.id,
            position=parsed_position,
            planned_title=clean_title,
            planned_author_name=clean_optional(planned_author_name),
            planned_format=planned_format,
            notes=clean_optional(notes),
        )
    )
    db.commit()
    return series_detail_redirect(series.id, message=f"Added planned book: {clean_title}")


@router.post("/{series_id}/planned/{entry_id}/edit")
async def update_planned_series_entry(
    series_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    planned_title: str = Form(default=""),
    planned_author_name: str | None = Form(default=None),
    planned_format: str = Form(default="unknown"),
    position: str | None = Form(default=None),
    notes: str | None = Form(default=None),
) -> Response:
    series = get_local_series(db, series_id)
    if series is None:
        return series_redirect(error="Series not found.")

    entry = get_series_entry(db, series, entry_id)
    if entry is None or entry.book_id is not None:
        return series_detail_redirect(series.id, error="Planned entry not found.")

    clean_title, parsed_position, errors = validate_planned_entry_form(planned_title, planned_format, position)
    if errors:
        return series_detail_redirect(series.id, error=errors[0])

    entry.position = parsed_position
    entry.planned_title = clean_title
    entry.planned_author_name = clean_optional(planned_author_name)
    entry.planned_format = planned_format
    entry.notes = clean_optional(notes)
    db.commit()
    return series_detail_redirect(series.id, message=f"Updated planned book: {clean_title}")


@router.post("/{series_id}/planned/{entry_id}/remove")
async def remove_planned_series_entry(
    series_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> Response:
    series = get_local_series(db, series_id)
    if series is None:
        return series_redirect(error="Series not found.")

    entry = get_series_entry(db, series, entry_id)
    if entry is None or entry.book_id is not None:
        return series_detail_redirect(series.id, error="Planned entry not found.")

    db.delete(entry)
    db.commit()
    return series_detail_redirect(series.id, message="Removed planned book from this series.")


@router.post("/{series_id}/planned/{entry_id}/convert")
async def convert_planned_entry_to_existing_book(
    series_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    book_id: int = Form(...),
) -> Response:
    series = get_local_series(db, series_id)
    if series is None:
        return series_redirect(error="Series not found.")

    entry = get_series_entry(db, series, entry_id)
    if entry is None or entry.book_id is not None:
        return series_detail_redirect(series.id, error="Planned entry not found.")

    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return series_detail_redirect(series.id, error="Book not found.")

    existing = db.scalars(
        select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.book_id == book.id)
    ).first()
    if existing is not None:
        return series_detail_redirect(series.id, error=f"{book.title} is already in this series.")

    entry.book_id = book.id
    entry.planned_title = None
    entry.planned_author_name = None
    entry.planned_format = None
    db.commit()
    return series_detail_redirect(series.id, message=f"Converted planned entry to {book.title}.")


@router.post("/{series_id}/libby/populate")
async def populate_series_from_libby_page(
    series_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    libby_series_page_content: str = Form(default=""),
    libby_series_snapshot_id: int | None = Form(default=None),
    use_latest_snapshot: bool = Form(default=False),
    include_unmatched: bool = Form(default=False),
    confirm: str | None = Form(default=None),
) -> Response:
    series = db.scalars(get_local_series_statement(series_id)).unique().one_or_none()
    if series is None:
        return series_redirect(error="Series not found.")

    snapshot: LibbySeriesSnapshot | None = None
    if libby_series_snapshot_id is not None:
        snapshot = db.get(LibbySeriesSnapshot, libby_series_snapshot_id)
        if snapshot is None or snapshot.series_id != series.id or snapshot.user_id != DEFAULT_LOCAL_USER_ID:
            return series_detail_redirect(series.id, error="Libby series snapshot not found.")
    elif use_latest_snapshot:
        snapshot = latest_libby_series_snapshot(db, series_id=series.id, user_id=DEFAULT_LOCAL_USER_ID)
        if snapshot is None:
            return series_detail_redirect(series.id, error="No scraped Libby series page is available yet.")

    content = libby_series_page_content
    if snapshot is not None:
        content = read_libby_series_snapshot_content(snapshot)

    if not clean_optional(content):
        return series_detail_redirect(series.id, error="Libby series page HTML is required.")

    if confirm == "true":
        result = apply_libby_series_population(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=content,
            include_unmatched=include_unmatched,
        )
        db.commit()
        return series_detail_redirect(
            series.id,
            message=(
                "Libby series population applied: "
                f"{result.added_books} books added, {result.added_planned} planned entries added, {result.skipped} skipped."
            ),
        )

    preview = build_libby_series_population_preview(
        db,
        user_id=DEFAULT_LOCAL_USER_ID,
        series_id=series.id,
        content=content,
        include_unmatched=include_unmatched,
    )
    return render_series_detail_view(
        request=request,
        db=db,
        series=series,
        book_q=None,
        message="Preview Libby series population before applying.",
        error=None,
        libby_series_preview=preview,
        libby_series_page_content="" if snapshot is not None else libby_series_page_content,
        libby_include_unmatched=include_unmatched,
        libby_series_snapshot_id=snapshot.id if snapshot is not None else None,
    )


@router.post("/{series_id}/libby/scrape")
def scrape_series_libby_page(
    series_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    libby_series_url: str = Form(default=""),
) -> Response:
    series = db.scalars(get_local_series_statement(series_id)).unique().one_or_none()
    if series is None:
        return series_redirect(error="Series not found.")
    clean_url = clean_optional(libby_series_url)
    if clean_url is None:
        return series_detail_redirect(series.id, error="Libby series URL is required.")
    try:
        result = libby_scrape_runner.scrape_libby_series_page(
            db,
            series=series,
            libby_series_url=clean_url,
            profile_dir=request.app.state.settings.libby_browser_profile_dir,
            scraped_dir=request.app.state.settings.scraped_dir,
        )
    except Exception as exc:
        db.rollback()
        return series_detail_redirect(series.id, error=f"Libby series scrape failed: {exc}")
    db.commit()
    return series_detail_redirect(
        series.id,
        message=f"Scraped Libby series page with {result['entry_count']} unique parsed works. Preview the latest scraped page to apply changes.",
    )


@router.get("/{series_id}", response_class=HTMLResponse)
async def series_detail(
    series_id: int,
    request: Request,
    db: Session = Depends(get_db),
    book_q: str | None = Query(default=None),
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    series = db.scalars(get_local_series_statement(series_id)).unique().one_or_none()
    if series is None:
        return templates.TemplateResponse(
            request,
            "series/not_found.html",
            template_context(request, page_title="Series Not Found"),
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    return render_series_detail_view(
        request=request,
        db=db,
        series=series,
        book_q=book_q,
        message=message,
        error=error,
    )
