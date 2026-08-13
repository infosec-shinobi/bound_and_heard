from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import Book, ReadingEvent, ScrapeJob, ScrapeJobItem
from app.services.libby_browser import LibbyBrowserError, open_libby_browser_session


router = APIRouter(prefix="/scraping", tags=["scraping"])
ACTIVE_SCRAPE_JOB_STATUSES = {"pending", "running"}
SCRAPE_JOB_ITEM_STATUSES = ["queued", "running", "succeeded", "failed", "skipped"]


def latest_libby_borrowed_dates(db: Session) -> dict[int, object]:
    rows = db.execute(
        select(ReadingEvent.book_id, func.max(ReadingEvent.event_date))
        .where(
            ReadingEvent.user_id == DEFAULT_LOCAL_USER_ID,
            ReadingEvent.source == "libby",
            ReadingEvent.event_type == "borrowed",
        )
        .group_by(ReadingEvent.book_id)
    ).all()
    return {book_id: borrowed_at for book_id, borrowed_at in rows}


def libby_scrape_candidate_context(db: Session) -> dict[str, object]:
    books = db.scalars(
        select(Book)
        .options(joinedload(Book.progress))
        .where(
            Book.user_id == DEFAULT_LOCAL_USER_ID,
            Book.metadata_source == "libby",
        )
        .order_by(Book.title.asc(), Book.id.asc())
    ).unique().all()
    latest_borrowed_by_book_id = latest_libby_borrowed_dates(db)

    queued: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    ineligible: list[dict[str, object]] = []

    for book in books:
        latest_borrowed_at = latest_borrowed_by_book_id.get(book.id)
        has_source_context = bool(book.libby_title_id or book.libby_share_url)
        row = {"book": book, "latest_borrowed_at": latest_borrowed_at}

        if book.archived_at is not None:
            skipped.append({**row, "reason": "Archived"})
        elif book.review_status == "ignored":
            skipped.append({**row, "reason": "Marked ignored"})
        elif not has_source_context:
            ineligible.append({**row, "reason": "Missing Libby title ID or share URL"})
        elif latest_borrowed_at is None:
            ineligible.append({**row, "reason": "Missing Libby borrow event"})
        else:
            queued.append(row)

    return {
        "queued": queued,
        "skipped": skipped,
        "ineligible": ineligible,
    }


def active_libby_scrape_job(db: Session) -> ScrapeJob | None:
    return db.scalars(
        select(ScrapeJob)
        .where(
            ScrapeJob.user_id == DEFAULT_LOCAL_USER_ID,
            ScrapeJob.source == "libby",
            ScrapeJob.status.in_(ACTIVE_SCRAPE_JOB_STATUSES),
        )
        .order_by(ScrapeJob.created_at.asc(), ScrapeJob.id.asc())
    ).first()


def scrape_item_status_counts(items: list[ScrapeJobItem]) -> dict[str, int]:
    counts = {item_status: 0 for item_status in SCRAPE_JOB_ITEM_STATUSES}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


@router.get("/libby/session", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def libby_session_page(
    request: Request,
    launched: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "scraping/libby_session.html",
        template_context(
            request,
            page_title="Libby Browser Session",
            profile_dir=request.app.state.settings.libby_browser_profile_dir,
            launched=launched,
            error=error,
        ),
    )


@router.post("/libby/session/open", dependencies=[Depends(require_write_access)])
async def open_libby_session(request: Request) -> Response:
    try:
        open_libby_browser_session(request.app.state.settings.libby_browser_profile_dir)
    except LibbyBrowserError as exc:
        query = urlencode({"error": str(exc)})
        return RedirectResponse(
            f"/scraping/libby/session?{query}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse("/scraping/libby/session?launched=true", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/libby/jobs/new", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def new_libby_scrape_job(
    request: Request,
    db: Session = Depends(get_db),
    created_job_id: int | None = None,
) -> HTMLResponse:
    candidate_context = libby_scrape_candidate_context(db)
    active_job = active_libby_scrape_job(db)
    return templates.TemplateResponse(
        request,
        "scraping/libby_job_new.html",
        template_context(
            request,
            page_title="New Libby Scrape Job",
            created_job_id=created_job_id,
            queued=candidate_context["queued"],
            skipped=candidate_context["skipped"],
            ineligible=candidate_context["ineligible"],
            active_job=active_job,
        ),
    )


@router.post("/libby/jobs", dependencies=[Depends(require_write_access)])
async def create_libby_scrape_job(db: Session = Depends(get_db)) -> Response:
    active_job = active_libby_scrape_job(db)
    if active_job is not None:
        return RedirectResponse(
            f"/scraping/libby/jobs/{active_job.id}?{urlencode({'message': 'An active Libby scrape job already exists.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    candidate_context = libby_scrape_candidate_context(db)
    queued = candidate_context["queued"]
    skipped = candidate_context["skipped"]
    ineligible = candidate_context["ineligible"]
    if not queued:
        return RedirectResponse("/scraping/libby/jobs/new", status_code=status.HTTP_303_SEE_OTHER)

    job = ScrapeJob(
        user_id=DEFAULT_LOCAL_USER_ID,
        source="libby",
        status="pending",
        summary={
            "queued_count": len(queued),
            "skipped_count": len(skipped),
            "ineligible_count": len(ineligible),
            "queued_book_ids": [row["book"].id for row in queued],
            "process_mode": "one_item_at_a_time",
        },
    )
    db.add(job)
    db.flush()
    for row in queued:
        book = row["book"]
        db.add(
            ScrapeJobItem(
                job_id=job.id,
                book_id=book.id,
                status="queued",
                latest_borrowed_at=row["latest_borrowed_at"],
                last_scraped_borrowed_at=book.progress.last_scraped_borrowed_at if book.progress else None,
            )
        )
    db.commit()
    return RedirectResponse(
        f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Scrape job created.'})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/libby/jobs/{job_id}", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def libby_scrape_job_detail(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    message: str | None = None,
) -> HTMLResponse:
    job = db.scalars(
        select(ScrapeJob)
        .options(joinedload(ScrapeJob.items).joinedload(ScrapeJobItem.book))
        .where(
            ScrapeJob.id == job_id,
            ScrapeJob.user_id == DEFAULT_LOCAL_USER_ID,
            ScrapeJob.source == "libby",
        )
    ).unique().first()
    if job is None:
        return templates.TemplateResponse(
            request,
            "scraping/job_not_found.html",
            template_context(request, page_title="Scrape Job Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    items = sorted(job.items, key=lambda item: (item.queued_at, item.id))
    return templates.TemplateResponse(
        request,
        "scraping/libby_job_detail.html",
        template_context(
            request,
            page_title=f"Libby Scrape Job #{job.id}",
            job=job,
            items=items,
            status_counts=scrape_item_status_counts(items),
            item_statuses=SCRAPE_JOB_ITEM_STATUSES,
            message=message,
        ),
    )
