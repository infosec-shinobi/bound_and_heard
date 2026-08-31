from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse, RedirectResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import Recap
from app.services.recap_service import (
    RecapAlreadyExistsError,
    export_recap_markdown,
    generate_quarterly_recap,
    generate_yearly_recap,
)


router = APIRouter(prefix="/recaps", tags=["recaps"])


def format_count(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return "Not available"


def format_hours(value: object) -> str:
    if not isinstance(value, int):
        return "Not available"
    if value <= 0:
        return "0 hr"
    hours = value / 3600
    if hours < 10 and not hours.is_integer():
        return f"{hours:.1f} hr"
    return f"{round(hours):,} hr"


def recap_response(request: Request, recap: Recap) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "recaps/detail.html",
        template_context(
            request,
            page_title=recap.title,
            recap=recap,
            payload=recap.payload or {},
            message=request.query_params.get("message"),
            error=request.query_params.get("error"),
            format_count=format_count,
            format_hours=format_hours,
        ),
    )


def recaps_redirect(**params: str) -> RedirectResponse:
    query = urlencode(params)
    target = "/recaps"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def recap_detail_redirect(recap: Recap, **params: str) -> RedirectResponse:
    if recap.period_type == "quarter":
        target = f"/recaps/quarter/{recap.year}/{recap.quarter}"
    else:
        target = f"/recaps/year/{recap.year}"
    query = urlencode(params)
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("", response_class=HTMLResponse)
async def recaps_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    recaps = db.scalars(
        select(Recap)
        .where(Recap.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(Recap.year.desc(), Recap.quarter.desc(), Recap.period_type.asc())
    ).all()
    return templates.TemplateResponse(
        request,
        "recaps/index.html",
        template_context(
            request,
            page_title="Recaps",
            recaps=recaps,
            current_year=date.today().year,
            message=request.query_params.get("message"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/generate", dependencies=[Depends(require_write_access)])
async def generate_recap_action(
    request: Request,
    db: Session = Depends(get_db),
    period_type: str = Form(...),
    year: int = Form(...),
    quarter: int = Form(1),
    overwrite: str | None = Form(None),
) -> RedirectResponse:
    try:
        if period_type == "quarter":
            recap = generate_quarterly_recap(
                db,
                user_id=DEFAULT_LOCAL_USER_ID,
                year=year,
                quarter=quarter,
                output_dir=request.app.state.settings.recaps_dir,
                overwrite=overwrite == "yes",
            )
        elif period_type == "year":
            recap = generate_yearly_recap(
                db,
                user_id=DEFAULT_LOCAL_USER_ID,
                year=year,
                output_dir=request.app.state.settings.recaps_dir,
                overwrite=overwrite == "yes",
            )
        else:
            return recaps_redirect(error="Choose yearly or quarterly recap generation.")
    except RecapAlreadyExistsError as exc:
        return recaps_redirect(error=f"{exc}. Check overwrite to regenerate it.")
    except ValueError as exc:
        return recaps_redirect(error=str(exc))

    db.commit()
    return recap_detail_redirect(recap, message=f"Generated {recap.title}.")


@router.post("/{recap_id}/export", dependencies=[Depends(require_write_access)])
async def export_recap_action(request: Request, recap_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    recap = db.scalar(select(Recap).where(Recap.id == recap_id, Recap.user_id == DEFAULT_LOCAL_USER_ID))
    if recap is None:
        raise HTTPException(status_code=404, detail="Recap not found")
    output_path = export_recap_markdown(recap, output_dir=request.app.state.settings.exports_dir)
    return recap_detail_redirect(recap, message=f"Exported Markdown recap to {output_path}.")


@router.get("/year/{year}", response_class=HTMLResponse)
async def yearly_recap(request: Request, year: int, db: Session = Depends(get_db)) -> HTMLResponse:
    recap = db.scalar(
        select(Recap).where(
            Recap.user_id == DEFAULT_LOCAL_USER_ID,
            Recap.period_type == "year",
            Recap.year == year,
            Recap.quarter == 0,
        )
    )
    if recap is None:
        raise HTTPException(status_code=404, detail="Recap not found")
    return recap_response(request, recap)


@router.get("/quarter/{year}/{quarter}", response_class=HTMLResponse)
async def quarterly_recap(request: Request, year: int, quarter: int, db: Session = Depends(get_db)) -> HTMLResponse:
    recap = db.scalar(
        select(Recap).where(
            Recap.user_id == DEFAULT_LOCAL_USER_ID,
            Recap.period_type == "quarter",
            Recap.year == year,
            Recap.quarter == quarter,
        )
    )
    if recap is None:
        raise HTTPException(status_code=404, detail="Recap not found")
    return recap_response(request, recap)
