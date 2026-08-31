from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.services.analytics import (
    PeriodRange,
    audiobook_seconds,
    books_completed_by_month,
    books_completed_by_period,
    format_breakdown,
    lifetime_enjoyed_seconds,
    pages_read,
    partial_progress_summary,
    quarter_range,
    repeat_counts,
    series_activity_summary,
    top_authors,
    top_genres,
    year_range,
)


router = APIRouter(prefix="/analytics", tags=["analytics"])


def period_from_query(period: str, year: int | None, quarter: int | None) -> tuple[PeriodRange, str, int | None, int | None]:
    today = date.today()
    if period == "quarter":
        selected_year = year or today.year
        selected_quarter = quarter if quarter in {1, 2, 3, 4} else ((today.month - 1) // 3) + 1
        return quarter_range(selected_year, selected_quarter), "quarter", selected_year, selected_quarter
    if period == "year":
        selected_year = year or today.year
        return year_range(selected_year), "year", selected_year, None
    return PeriodRange(), "all", year, None


def format_count(value: int) -> str:
    return f"{value:,}"


def format_hours(seconds: int) -> str:
    if seconds <= 0:
        return "0 hr"
    hours = seconds / 3600
    if hours < 10 and not hours.is_integer():
        return f"{hours:.1f} hr"
    return f"{round(hours):,} hr"


@router.get("", response_class=HTMLResponse)
async def analytics_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    period: str = Query("year"),
    year: int | None = Query(None),
    quarter: int | None = Query(None),
) -> HTMLResponse:
    selected_period, period_key, selected_year, selected_quarter = period_from_query(period, year, quarter)
    month_year = selected_year if period_key in {"year", "quarter"} else None
    partial_summary = partial_progress_summary(db, user_id=DEFAULT_LOCAL_USER_ID)
    repeats = repeat_counts(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period)
    series_summary = series_activity_summary(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period)

    return templates.TemplateResponse(
        request,
        "analytics/dashboard.html",
        template_context(
            request,
            page_title="Analytics",
            period_key=period_key,
            selected_year=selected_year,
            selected_quarter=selected_quarter,
            current_year=date.today().year,
            completed_count=books_completed_by_period(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period),
            month_counts=books_completed_by_month(db, user_id=DEFAULT_LOCAL_USER_ID, year=month_year),
            format_counts=format_breakdown(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period),
            top_authors=top_authors(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period),
            top_genres=top_genres(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period),
            pages_total=pages_read(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period),
            audiobook_seconds_total=audiobook_seconds(db, user_id=DEFAULT_LOCAL_USER_ID, period=selected_period),
            lifetime_enjoyed_seconds_total=lifetime_enjoyed_seconds(db, user_id=DEFAULT_LOCAL_USER_ID),
            partial_summary=partial_summary,
            repeats=repeats,
            series_summary=series_summary,
            format_count=format_count,
            format_hours=format_hours,
        ),
    )
