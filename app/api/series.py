from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.models import Book, Series, SeriesBook


router = APIRouter(prefix="/series", tags=["series"])

SERIES_STATUSES = ["active", "paused", "completed", "abandoned", "unknown"]


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


@router.get("", response_class=HTMLResponse)
async def series_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
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
        ),
    )
