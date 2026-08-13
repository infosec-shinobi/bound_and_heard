from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import Book, BookProgress, ReadingEvent, ScrapeJob, ScrapeJobItem, ScrapeSnapshot
from app.services import libby_scrape_runner
from app.services.libby_browser import LibbyBrowserError, open_libby_browser_session
from app.services.scrape_safety import scrape_safety_summary


router = APIRouter(prefix="/scraping", tags=["scraping"])
ACTIVE_SCRAPE_JOB_STATUSES = {"pending", "running"}
SCRAPE_JOB_ITEM_STATUSES = ["queued", "running", "succeeded", "failed", "skipped"]
RECOVERABLE_JOB_STATUSES = {"failed", "cancelled", "completed"}


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


def should_skip_unchanged_book(book: Book, latest_borrowed_at: object) -> bool:
    if book.progress is None or book.progress.last_scraped_borrowed_at is None:
        return False
    return latest_borrowed_at <= book.progress.last_scraped_borrowed_at


def parsed_snapshot_has_progress(raw_data: dict | None) -> bool:
    parsed = (raw_data or {}).get("parsed_progress") or {}
    return any(parsed.get(field_name) is not None for field_name in ("progress_percent", "position_pages", "position_seconds"))


def item_has_parseable_progress_snapshot(item: ScrapeJobItem) -> bool:
    return any(parsed_snapshot_has_progress(snapshot.raw_data) for snapshot in item.snapshots)


def empty_scraped_progress(progress: BookProgress | None) -> bool:
    if progress is None or progress.source != "scraped":
        return False
    return all(
        getattr(progress, field_name) is None
        for field_name in ("progress_percent", "position_pages", "total_pages", "position_seconds", "total_seconds", "status_inferred")
    )


def libby_scrape_candidate_context(db: Session, *, force: bool = False) -> dict[str, object]:
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
        has_source_context = bool(book.libby_title_id)
        last_scraped_borrowed_at = book.progress.last_scraped_borrowed_at if book.progress else None
        row = {
            "book": book,
            "latest_borrowed_at": latest_borrowed_at,
            "last_scraped_borrowed_at": last_scraped_borrowed_at,
        }

        if book.archived_at is not None:
            skipped.append({**row, "reason": "Archived"})
        elif book.review_status == "ignored":
            skipped.append({**row, "reason": "Marked ignored"})
        elif not has_source_context:
            ineligible.append({**row, "reason": "Missing Libby title ID"})
        elif latest_borrowed_at is None:
            ineligible.append({**row, "reason": "Missing Libby borrow event"})
        elif not force and should_skip_unchanged_book(book, latest_borrowed_at):
            skipped.append({**row, "reason": "Latest borrow already scraped"})
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


def retryable_libby_scrape_item_ids(items: list[ScrapeJobItem]) -> set[int]:
    return {
        item.id
        for item in items
        if item.status in {"failed", "skipped"}
        or (item.status == "succeeded" and not item_has_parseable_progress_snapshot(item))
    }


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


@router.get("/libby/jobs", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def libby_scrape_jobs_index(
    request: Request,
    db: Session = Depends(get_db),
    message: str | None = None,
) -> HTMLResponse:
    jobs = db.scalars(
        select(ScrapeJob)
        .options(joinedload(ScrapeJob.items).joinedload(ScrapeJobItem.snapshots))
        .where(
            ScrapeJob.user_id == DEFAULT_LOCAL_USER_ID,
            ScrapeJob.source == "libby",
        )
        .order_by(ScrapeJob.created_at.desc(), ScrapeJob.id.desc())
    ).unique().all()
    job_rows = []
    for job in jobs:
        items = list(job.items)
        counts = scrape_item_status_counts(items)
        retryable_count = len(retryable_libby_scrape_item_ids(items))
        job_rows.append(
            {
                "job": job,
                "item_count": len(items),
                "status_counts": counts,
                "retryable_count": retryable_count,
            }
        )
    return templates.TemplateResponse(
        request,
        "scraping/libby_jobs_index.html",
        template_context(
            request,
            page_title="Libby Scrape Jobs",
            job_rows=job_rows,
            active_job=active_libby_scrape_job(db),
            message=message,
        ),
    )


@router.get("/libby/jobs/new", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def new_libby_scrape_job(
    request: Request,
    db: Session = Depends(get_db),
    created_job_id: int | None = None,
    force: bool = Query(default=False),
) -> HTMLResponse:
    candidate_context = libby_scrape_candidate_context(db, force=force)
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
            force=force,
        ),
    )


@router.post("/libby/jobs", dependencies=[Depends(require_write_access)])
async def create_libby_scrape_job(
    db: Session = Depends(get_db),
    force: bool = Form(default=False),
    selected_book_ids: list[int] | None = Form(default=None, alias="book_ids"),
) -> Response:
    active_job = active_libby_scrape_job(db)
    if active_job is not None:
        return RedirectResponse(
            f"/scraping/libby/jobs/{active_job.id}?{urlencode({'message': 'An active Libby scrape job already exists.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    candidate_context = libby_scrape_candidate_context(db, force=force)
    queued = candidate_context["queued"]
    skipped = candidate_context["skipped"]
    ineligible = candidate_context["ineligible"]
    if selected_book_ids:
        selected_book_id_set = set(selected_book_ids)
        skipped.extend(
            {**row, "reason": "Not selected for this job"}
            for row in queued
            if row["book"].id not in selected_book_id_set
        )
        queued = [row for row in queued if row["book"].id in selected_book_id_set]
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
            "force": force,
            "selected_book_ids": selected_book_ids or [],
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
                last_scraped_borrowed_at=row["last_scraped_borrowed_at"],
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
        .options(
            joinedload(ScrapeJob.items).joinedload(ScrapeJobItem.book),
            joinedload(ScrapeJob.items).joinedload(ScrapeJobItem.snapshots),
        )
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
    retryable_item_ids = retryable_libby_scrape_item_ids(items)
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
            can_cancel=job.status in ACTIVE_SCRAPE_JOB_STATUSES,
            can_start=job.status == "pending" and bool(items),
            can_recover=job.status in RECOVERABLE_JOB_STATUSES and any(item.status in {"queued", "running", "failed", "skipped"} for item in items),
            retryable_item_ids=retryable_item_ids,
            safety=scrape_safety_summary(),
            snapshot_dir=request.app.state.settings.scraped_dir,
            message=message,
        ),
    )


@router.post("/libby/jobs/{job_id}/start", dependencies=[Depends(require_write_access)])
def start_libby_scrape_job(job_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
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
        return RedirectResponse("/scraping/libby/jobs/new", status_code=status.HTTP_303_SEE_OTHER)
    if job.status != "pending":
        return RedirectResponse(
            f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Only pending jobs can be started.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if not job.items:
        return RedirectResponse(
            f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'This job has no queued items to start.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    now = datetime.now(timezone.utc)
    job.status = "running"
    job.started_at = job.started_at or now
    summary = dict(job.summary or {})
    summary["started_by_user_at"] = now.isoformat()
    summary["safety"] = scrape_safety_summary()
    summary["automatic_retries"] = False
    job.summary = summary
    db.commit()

    try:
        run_summary = libby_scrape_runner.run_libby_scrape_job(
            db,
            job=job,
            profile_dir=request.app.state.settings.libby_browser_profile_dir,
            scraped_dir=request.app.state.settings.scraped_dir,
        )
    except Exception as exc:
        now = datetime.now(timezone.utc)
        job.status = "failed"
        job.finished_at = now
        for item in job.items:
            if item.status == "running":
                item.status = "failed"
                item.finished_at = now
                item.error_code = exc.__class__.__name__
                item.error_message = str(exc)
        summary = dict(job.summary or {})
        summary["runner_error"] = str(exc)
        job.summary = summary
        db.commit()
        return RedirectResponse(
            f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Scrape job failed to start.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    job.status = "completed" if job.status == "running" else job.status
    job.finished_at = datetime.now(timezone.utc) if job.status == "completed" else job.finished_at
    summary = dict(job.summary or {})
    summary["run"] = run_summary
    job.summary = summary
    db.commit()
    return RedirectResponse(
        f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Scrape job completed.'})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/libby/jobs/{job_id}/cancel", dependencies=[Depends(require_write_access)])
async def cancel_libby_scrape_job(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.scalars(
        select(ScrapeJob)
        .options(joinedload(ScrapeJob.items))
        .where(
            ScrapeJob.id == job_id,
            ScrapeJob.user_id == DEFAULT_LOCAL_USER_ID,
            ScrapeJob.source == "libby",
        )
    ).unique().first()
    if job is None:
        return RedirectResponse("/scraping/libby/jobs/new", status_code=status.HTTP_303_SEE_OTHER)
    if job.status not in ACTIVE_SCRAPE_JOB_STATUSES:
        return RedirectResponse(
            f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Only pending or running jobs can be cancelled.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    now = datetime.now(timezone.utc)
    job.status = "cancelled"
    job.finished_at = now
    summary = dict(job.summary or {})
    summary["cancelled_at"] = now.isoformat()
    job.summary = summary
    for item in job.items:
        if item.status in {"queued", "running"}:
            item.status = "skipped"
            item.finished_at = now
            item.error_code = "job_cancelled"
            item.error_message = "Scrape job was cancelled before this item completed."
    db.commit()
    return RedirectResponse(
        f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Scrape job cancelled.'})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/libby/jobs/{job_id}/recover", dependencies=[Depends(require_write_access)])
async def recover_libby_scrape_job(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.scalars(
        select(ScrapeJob)
        .options(joinedload(ScrapeJob.items))
        .where(
            ScrapeJob.id == job_id,
            ScrapeJob.user_id == DEFAULT_LOCAL_USER_ID,
            ScrapeJob.source == "libby",
        )
    ).unique().first()
    if job is None:
        return RedirectResponse("/scraping/libby/jobs", status_code=status.HTTP_303_SEE_OTHER)
    if job.status == "running":
        return RedirectResponse(
            f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Running jobs must be cancelled before recovery.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    recovered_count = 0
    for item in job.items:
        if item.status in {"queued", "running", "failed", "skipped"}:
            item.status = "queued"
            item.error_code = None
            item.error_message = None
            item.started_at = None
            item.finished_at = None
            recovered_count += 1
    if recovered_count:
        job.status = "pending"
        job.finished_at = None
        summary = dict(job.summary or {})
        summary.pop("runner_error", None)
        summary["recovered_at"] = datetime.now(timezone.utc).isoformat()
        summary["recovered_item_count"] = recovered_count
        job.summary = summary
        db.commit()
        message = f"Recovered {recovered_count} item{'s' if recovered_count != 1 else ''}."
    else:
        message = "No recoverable items found."
    return RedirectResponse(
        f"/scraping/libby/jobs/{job.id}?{urlencode({'message': message})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/libby/jobs/{job_id}/delete", dependencies=[Depends(require_write_access)])
async def delete_libby_scrape_job(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = db.scalars(
        select(ScrapeJob)
        .options(joinedload(ScrapeJob.items))
        .where(
            ScrapeJob.id == job_id,
            ScrapeJob.user_id == DEFAULT_LOCAL_USER_ID,
            ScrapeJob.source == "libby",
        )
    ).unique().first()
    if job is None:
        return RedirectResponse("/scraping/libby/jobs", status_code=status.HTTP_303_SEE_OTHER)
    if job.status == "running":
        return RedirectResponse(
            f"/scraping/libby/jobs/{job.id}?{urlencode({'message': 'Running jobs must be cancelled before deletion.'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    item_ids = [item.id for item in job.items]
    if item_ids:
        db.execute(delete(ScrapeSnapshot).where(ScrapeSnapshot.item_id.in_(item_ids)))
        db.execute(delete(ScrapeJobItem).where(ScrapeJobItem.id.in_(item_ids)))
    db.delete(job)
    db.commit()
    return RedirectResponse(
        f"/scraping/libby/jobs?{urlencode({'message': f'Scrape job #{job_id} deleted.'})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/libby/jobs/{job_id}/items/{item_id}/requeue", dependencies=[Depends(require_write_access)])
async def requeue_skipped_libby_scrape_item(job_id: int, item_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.scalars(
        select(ScrapeJobItem)
        .options(joinedload(ScrapeJobItem.book).joinedload(Book.progress), joinedload(ScrapeJobItem.snapshots))
        .join(ScrapeJob)
        .where(
            ScrapeJobItem.id == item_id,
            ScrapeJobItem.job_id == job_id,
            ScrapeJob.user_id == DEFAULT_LOCAL_USER_ID,
            ScrapeJob.source == "libby",
        )
    ).first()
    if item is None:
        return RedirectResponse(f"/scraping/libby/jobs/{job_id}", status_code=status.HTTP_303_SEE_OTHER)
    can_requeue = item.status in {"skipped", "failed"} or (item.status == "succeeded" and not item_has_parseable_progress_snapshot(item))
    if can_requeue:
        item.status = "queued"
        item.error_code = None
        item.error_message = None
        item.started_at = None
        item.finished_at = None
        if empty_scraped_progress(item.book.progress):
            item.book.progress.last_scraped_borrowed_at = None
        if item.job.status in {"completed", "cancelled"}:
            item.job.status = "pending"
            item.job.finished_at = None
        db.commit()
        message = "Item requeued."
    else:
        message = "Only skipped, failed, or empty successful items can be requeued."
    return RedirectResponse(
        f"/scraping/libby/jobs/{job_id}?{urlencode({'message': message})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
