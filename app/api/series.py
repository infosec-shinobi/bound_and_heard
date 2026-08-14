from dataclasses import dataclass
from datetime import date
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
from app.models import Book, Series, SeriesBook


router = APIRouter(prefix="/series", tags=["series"])

SERIES_STATUSES = ["active", "paused", "completed", "abandoned", "unknown"]
CONTINUATION_INTENTS = ["yes", "no", "unknown"]


@dataclass(frozen=True)
class SeriesListItem:
    series: Series
    completed_count: int
    total_count: int
    next_unread_title: str | None
    next_unread_author: str | None


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


def is_series_entry_completed(entry: SeriesBook) -> bool:
    if entry.book is None:
        return False
    if entry.book.status == "completed":
        return True
    return bool(entry.book.progress and entry.book.progress.progress_percent == 100)


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
    completed_count = sum(1 for entry in entries if is_series_entry_completed(entry))
    next_unread = next((entry for entry in entries if not is_series_entry_completed(entry)), None)

    return SeriesListItem(
        series=series,
        completed_count=completed_count,
        total_count=len(entries),
        next_unread_title=series_entry_title(next_unread) if next_unread else None,
        next_unread_author=series_entry_author(next_unread) if next_unread else None,
    )


def build_series_detail_entries(series: Series) -> list[SeriesDetailEntry]:
    entries = sorted(series.books, key=series_entry_sort_key)
    next_unread = next((entry for entry in entries if not is_series_entry_completed(entry)), None)
    detail_entries: list[SeriesDetailEntry] = []

    for entry in entries:
        is_planned = entry.book is None
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
                is_completed=is_series_entry_completed(entry),
                is_next_unread=entry is next_unread,
            )
        )

    return detail_entries


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

    entries = build_series_detail_entries(series)
    completed_count = sum(1 for entry in entries if entry.is_completed)
    next_unread = next((entry for entry in entries if entry.is_next_unread), None)
    selectable_books = db.scalars(selectable_books_statement(book_q)).all()

    return templates.TemplateResponse(
        request,
        "series/detail.html",
        template_context(
            request,
            page_title=series.name,
            series=series,
            entries=entries,
            completed_count=completed_count,
            total_count=len(entries),
            next_unread=next_unread,
            selectable_books=selectable_books,
            book_options={book.id: book_option_label(book) for book in selectable_books},
            book_q=book_q or "",
            message=message,
            error=error,
        ),
    )
