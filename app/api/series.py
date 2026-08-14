from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request, status as http_status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
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


def series_redirect(**params: str) -> RedirectResponse:
    return RedirectResponse(
        f"/series?{urlencode(params)}",
        status_code=http_status.HTTP_303_SEE_OTHER,
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
