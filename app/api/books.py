from datetime import date, datetime, time, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import Book, BookProgress, ReadingEvent


router = APIRouter(prefix="/books", tags=["books"])

BOOK_FORMATS = ["ebook", "audiobook", "physical", "unknown"]
BOOK_STATUSES = ["want_to_read", "borrowed", "started", "completed", "abandoned", "unknown"]
BOOK_SOURCE_FILTERS = {
    "libby": "Libby",
    "manual": "Manual",
    "missing": "Missing source",
}
REVIEW_METADATA_FILTERS = {
    "missing_page_count": "Missing page count",
    "missing_audio_duration": "Missing audio duration",
    "missing_author": "Missing author",
    "missing_publisher": "Missing publisher",
    "missing_isbn": "Missing ISBN",
    "missing_cover_url": "Missing cover URL",
}
REVIEW_SUSPICIOUS_FILTERS = {
    "unknown_format": "Unknown format",
    "unknown_status": "Unknown status",
    "missing_libby_title_id": "Missing Libby title ID",
    "fallback_title": "Fallback title",
    "no_reading_events": "No reading events",
    "completed_without_completion_date": "Completed without completion date",
    "progress_status_mismatch": "Progress/status mismatch",
    "duplicate_candidate": "Duplicate candidate",
}
TITLE_FALLBACK_VALUES = ["untitled libby book"]
WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_duplicate_text(value: str | None) -> str | None:
    value = clean_optional(value)
    if value is None:
        return None
    return WHITESPACE_PATTERN.sub(" ", value.casefold())


def add_duplicate_reason(
    duplicate_reasons: dict[int, list[str]],
    books: list[Book],
    reason: str,
) -> None:
    if len(books) < 2:
        return
    for book in books:
        duplicate_reasons.setdefault(book.id, []).append(reason)


def duplicate_reasons_by_book_id(books: list[Book]) -> dict[int, list[str]]:
    duplicate_reasons: dict[int, list[str]] = {}
    libby_title_format_groups: dict[tuple[str, str], list[Book]] = {}
    title_author_format_groups: dict[tuple[str, str, str], list[Book]] = {}
    isbn_format_groups: dict[tuple[str, str], list[Book]] = {}

    for book in books:
        libby_title_id = clean_optional(book.libby_title_id)
        if libby_title_id is not None:
            libby_title_format_groups.setdefault((libby_title_id, book.format), []).append(book)

        normalized_title = normalize_duplicate_text(book.title)
        normalized_author = normalize_duplicate_text(book.primary_author_name)
        if normalized_title is not None and normalized_author is not None:
            title_author_format_groups.setdefault(
                (normalized_title, normalized_author, book.format),
                [],
            ).append(book)

        for isbn in (clean_optional(book.isbn10), clean_optional(book.isbn13)):
            if isbn is not None:
                isbn_format_groups.setdefault((isbn, book.format), []).append(book)

    for (title_id, book_format), grouped_books in libby_title_format_groups.items():
        add_duplicate_reason(duplicate_reasons, grouped_books, f"Same Libby title ID and format: {title_id} / {book_format}")
    for grouped_books in title_author_format_groups.values():
        add_duplicate_reason(duplicate_reasons, grouped_books, "Same normalized title, author, and format")
    for (isbn, book_format), grouped_books in isbn_format_groups.items():
        add_duplicate_reason(duplicate_reasons, grouped_books, f"Same ISBN and format: {isbn} / {book_format}")

    return duplicate_reasons


def parse_optional_date(value: str | None, field_name: str, errors: list[str]) -> date | None:
    value = clean_optional(value)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field_name} must be a valid date.")
        return None


def parse_optional_float(
    value: str | None,
    field_name: str,
    errors: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    value = clean_optional(value)
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        errors.append(f"{field_name} must be a number.")
        return None
    if minimum is not None and parsed < minimum:
        errors.append(f"{field_name} must be at least {minimum:g}.")
    if maximum is not None and parsed > maximum:
        errors.append(f"{field_name} must be no more than {maximum:g}.")
    return parsed


def parse_optional_int(
    value: str | None,
    field_name: str,
    errors: list[str],
    *,
    minimum: int | None = None,
) -> int | None:
    value = clean_optional(value)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        errors.append(f"{field_name} must be a whole number.")
        return None
    if minimum is not None and parsed < minimum:
        errors.append(f"{field_name} must be at least {minimum}.")
    return parsed


def parse_optional_isbn(value: str | None, errors: list[str]) -> tuple[str | None, str | None]:
    value = clean_optional(value)
    if value is None:
        return None, None

    normalized = "".join(character for character in value if character.isdigit() or character.upper() == "X")
    if len(normalized) == 10:
        return normalized, None
    if len(normalized) == 13 and normalized.isdigit():
        return None, normalized

    errors.append("ISBN must be a valid ISBN-10 or ISBN-13.")
    return None, None


def date_to_datetime(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def format_audio_seconds(audio_seconds: int | None) -> str | None:
    if audio_seconds is None:
        return None
    hours = audio_seconds // 3600
    minutes = round((audio_seconds % 3600) / 60)
    if minutes == 60:
        hours += 1
        minutes = 0
    if hours and minutes:
        return f"{hours} hr {minutes} min"
    if hours:
        return f"{hours} hr"
    return f"{minutes} min"


def display_progress(book: Book) -> float | None:
    if book.progress and book.progress.progress_percent is not None:
        return book.progress.progress_percent
    return book.manual_progress_percent


def missing_text_filter(column: object) -> object:
    return or_(column.is_(None), func.trim(column) == "")


def review_progress_expression() -> object:
    return func.coalesce(BookProgress.progress_percent, Book.manual_progress_percent)


def safe_review_return_url(value: str | None) -> str:
    if not value or not value.startswith("/books/review") or value.startswith("//"):
        return "/books/review"
    parsed = urlsplit(value)
    query_items = [(key, item_value) for key, item_value in parse_qsl(parsed.query) if key != "review_error"]
    return urlunsplit(("", "", parsed.path, urlencode(query_items), ""))


def review_return_url_with_error(return_url: str, message: str) -> str:
    parsed = urlsplit(return_url)
    query_items = parse_qsl(parsed.query)
    query_items.append(("review_error", message))
    return urlunsplit(("", "", parsed.path, urlencode(query_items), ""))


def audio_seconds_to_hours(audio_seconds: int | None) -> str:
    if audio_seconds is None:
        return ""
    return f"{audio_seconds / 3600:g}"


def book_form_values(book: Book) -> dict[str, str]:
    return {
        "title": book.title,
        "subtitle": book.subtitle or "",
        "primary_author_name": book.primary_author_name or "",
        "isbn": book.isbn13 or book.isbn10 or "",
        "format": book.format,
        "status": book.status,
        "rating": f"{book.rating:g}" if book.rating is not None else "",
        "notes": book.notes or "",
        "started_on": book.started_on.isoformat() if book.started_on else "",
        "completed_on": book.completed_on.isoformat() if book.completed_on else "",
        "page_count": str(book.page_count) if book.page_count is not None else "",
        "audio_hours": audio_seconds_to_hours(book.audio_seconds),
        "manual_progress_percent": f"{book.manual_progress_percent:g}"
        if book.manual_progress_percent is not None
        else "",
    }


def submitted_form_values(
    *,
    title: str,
    subtitle: str | None,
    primary_author_name: str | None,
    isbn: str | None,
    format: str,
    status_value: str,
    rating: str | None,
    notes: str | None,
    started_on: str | None,
    completed_on: str | None,
    page_count: str | None,
    audio_hours: str | None,
    manual_progress_percent: str | None,
) -> dict[str, str]:
    return {
        "title": title,
        "subtitle": subtitle or "",
        "primary_author_name": primary_author_name or "",
        "isbn": isbn or "",
        "format": format,
        "status": status_value,
        "rating": rating or "",
        "notes": notes or "",
        "started_on": started_on or "",
        "completed_on": completed_on or "",
        "page_count": page_count or "",
        "audio_hours": audio_hours or "",
        "manual_progress_percent": manual_progress_percent or "",
    }


def correction_event_for_changes(
    book: Book,
    *,
    old_status: str,
    old_completed_on: date | None,
    old_progress: float | None,
) -> ReadingEvent | None:
    changed_fields: dict[str, dict[str, object]] = {}
    if book.status != old_status:
        changed_fields["status"] = {"from": old_status, "to": book.status}
    if book.completed_on != old_completed_on:
        changed_fields["completed_on"] = {
            "from": old_completed_on.isoformat() if old_completed_on else None,
            "to": book.completed_on.isoformat() if book.completed_on else None,
        }
    if book.manual_progress_percent != old_progress:
        changed_fields["manual_progress_percent"] = {
            "from": old_progress,
            "to": book.manual_progress_percent,
        }

    if not changed_fields:
        return None

    return ReadingEvent(
        user_id=book.user_id,
        book_id=book.id,
        source="manual",
        event_type="manually_corrected",
        event_date=datetime.now(timezone.utc),
        progress_percent=book.manual_progress_percent,
        raw_data={"changed_fields": changed_fields},
    )


def build_initial_events(book: Book) -> list[ReadingEvent]:
    events: list[ReadingEvent] = []

    if book.started_on is not None:
        events.append(
            ReadingEvent(
                user_id=book.user_id,
                book_id=book.id,
                source="manual",
                event_type="started",
                event_date=date_to_datetime(book.started_on),
            )
        )

    if book.completed_on is not None or book.status == "completed":
        events.append(
            ReadingEvent(
                user_id=book.user_id,
                book_id=book.id,
                source="manual",
                event_type="manually_completed",
                event_date=date_to_datetime(book.completed_on) if book.completed_on else datetime.now(timezone.utc),
                progress_percent=100,
            )
        )
    elif book.status == "abandoned":
        events.append(
            ReadingEvent(
                user_id=book.user_id,
                book_id=book.id,
                source="manual",
                event_type="abandoned",
                event_date=datetime.now(timezone.utc),
                progress_percent=book.manual_progress_percent,
            )
        )
    elif book.manual_progress_percent is not None:
        events.append(
            ReadingEvent(
                user_id=book.user_id,
                book_id=book.id,
                source="manual",
                event_type="progress_seen",
                event_date=datetime.now(timezone.utc),
                progress_percent=book.manual_progress_percent,
            )
        )

    return events


def apply_book_filters(
    statement: Select[tuple[Book]],
    *,
    q: str | None,
    status: str | None,
    book_format: str | None,
    source: str | None,
    include_archived: bool,
) -> Select[tuple[Book]]:
    if not include_archived:
        statement = statement.where(Book.archived_at.is_(None))

    if q:
        search = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Book.title.ilike(search),
                Book.subtitle.ilike(search),
                Book.primary_author_name.ilike(search),
            )
        )

    if status:
        statement = statement.where(Book.status == status)

    if book_format:
        statement = statement.where(Book.format == book_format)

    if source == "missing":
        statement = statement.where(missing_text_filter(Book.metadata_source))
    elif source in BOOK_SOURCE_FILTERS:
        statement = statement.where(Book.metadata_source == source)

    return statement


@router.get("", response_class=HTMLResponse)
async def book_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    format: str | None = Query(default=None),
    source: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> HTMLResponse:
    statement = (
        select(Book)
        .options(joinedload(Book.progress))
        .where(Book.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(Book.title.asc())
    )
    statement = apply_book_filters(
        statement,
        q=q,
        status=status,
        book_format=format,
        source=source,
        include_archived=include_archived,
    )
    books = db.scalars(statement).unique().all()

    return templates.TemplateResponse(
        request,
        "books/list.html",
        template_context(
            request,
            page_title="Books",
            books=books,
            q=q or "",
            selected_status=status or "",
            selected_format=format or "",
            selected_source=source or "",
            book_statuses=BOOK_STATUSES,
            book_formats=BOOK_FORMATS,
            book_source_filters=BOOK_SOURCE_FILTERS,
            include_archived=include_archived,
        ),
    )


@router.get("/review", response_class=HTMLResponse)
async def imported_books_review(
    request: Request,
    db: Session = Depends(get_db),
    missing_page_count: bool = Query(default=False),
    missing_audio_duration: bool = Query(default=False),
    missing_author: bool = Query(default=False),
    missing_publisher: bool = Query(default=False),
    missing_isbn: bool = Query(default=False),
    missing_cover_url: bool = Query(default=False),
    unknown_format: bool = Query(default=False),
    unknown_status: bool = Query(default=False),
    missing_libby_title_id: bool = Query(default=False),
    fallback_title: bool = Query(default=False),
    no_reading_events: bool = Query(default=False),
    completed_without_completion_date: bool = Query(default=False),
    progress_status_mismatch: bool = Query(default=False),
    duplicate_candidate: bool = Query(default=False),
    review_error: str | None = Query(default=None),
) -> HTMLResponse:
    active_filters = {
        "missing_page_count": missing_page_count,
        "missing_audio_duration": missing_audio_duration,
        "missing_author": missing_author,
        "missing_publisher": missing_publisher,
        "missing_isbn": missing_isbn,
        "missing_cover_url": missing_cover_url,
        "unknown_format": unknown_format,
        "unknown_status": unknown_status,
        "missing_libby_title_id": missing_libby_title_id,
        "fallback_title": fallback_title,
        "no_reading_events": no_reading_events,
        "completed_without_completion_date": completed_without_completion_date,
        "progress_status_mismatch": progress_status_mismatch,
        "duplicate_candidate": duplicate_candidate,
    }

    duplicate_universe = db.scalars(
        select(Book).where(
            Book.user_id == DEFAULT_LOCAL_USER_ID,
            Book.archived_at.is_(None),
        )
    ).all()
    duplicate_reasons = duplicate_reasons_by_book_id(list(duplicate_universe))

    statement = (
        select(Book)
        .options(joinedload(Book.progress))
        .outerjoin(BookProgress, BookProgress.book_id == Book.id)
        .where(
            Book.user_id == DEFAULT_LOCAL_USER_ID,
            Book.archived_at.is_(None),
            Book.metadata_source == "libby",
            or_(Book.review_status.is_(None), Book.review_status.not_in(["reviewed", "ignored"])),
        )
        .order_by(Book.title.asc(), Book.id.asc())
    )

    if missing_page_count:
        statement = statement.where(Book.page_count.is_(None))
    if missing_audio_duration:
        statement = statement.where(Book.audio_seconds.is_(None))
    if missing_author:
        statement = statement.where(missing_text_filter(Book.primary_author_name))
    if missing_publisher:
        statement = statement.where(missing_text_filter(Book.publisher))
    if missing_isbn:
        statement = statement.where(missing_text_filter(Book.isbn10), missing_text_filter(Book.isbn13))
    if missing_cover_url:
        statement = statement.where(missing_text_filter(Book.cover_url))
    if unknown_format:
        statement = statement.where(Book.format == "unknown")
    if unknown_status:
        statement = statement.where(Book.status == "unknown")
    if missing_libby_title_id:
        statement = statement.where(missing_text_filter(Book.libby_title_id))
    if fallback_title:
        statement = statement.where(func.lower(func.trim(Book.title)).in_(TITLE_FALLBACK_VALUES))
    if no_reading_events:
        statement = statement.where(~Book.reading_events.any())
    if completed_without_completion_date:
        statement = statement.where(Book.status == "completed", Book.completed_on.is_(None))
    if progress_status_mismatch:
        progress = review_progress_expression()
        statement = statement.where(
            or_(
                and_(Book.status == "completed", progress.is_not(None), progress < 100),
                and_(Book.status != "completed", progress >= 100),
            )
        )
    if duplicate_candidate:
        duplicate_book_ids = list(duplicate_reasons)
        if duplicate_book_ids:
            statement = statement.where(Book.id.in_(duplicate_book_ids))
        else:
            statement = statement.where(Book.id == -1)

    books = db.scalars(statement).unique().all()

    return templates.TemplateResponse(
        request,
        "books/review.html",
        template_context(
            request,
            page_title="Import Review",
            books=books,
            metadata_filter_options=REVIEW_METADATA_FILTERS,
            suspicious_filter_options=REVIEW_SUSPICIOUS_FILTERS,
            active_filters=active_filters,
            book_statuses=BOOK_STATUSES,
            review_error=review_error,
            duplicate_reasons=duplicate_reasons,
            format_audio_seconds=format_audio_seconds,
        ),
    )


@router.post("/{book_id}/review/status")
async def update_review_book_status(
    book_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    status_value: str = Form(..., alias="status"),
    return_to: str | None = Form(default=None),
) -> Response:
    return_url = safe_review_return_url(return_to)
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)
    if status_value not in BOOK_STATUSES:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)

    old_status = book.status
    old_completed_on = book.completed_on
    old_progress = book.manual_progress_percent
    book.status = status_value

    correction_event = correction_event_for_changes(
        book,
        old_status=old_status,
        old_completed_on=old_completed_on,
        old_progress=old_progress,
    )
    if correction_event is not None:
        db.add(correction_event)

    db.commit()
    return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{book_id}/review/progress")
async def update_review_book_progress(
    book_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    manual_progress_percent: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
) -> Response:
    return_url = safe_review_return_url(return_to)
    errors: list[str] = []
    parsed_progress = parse_optional_float(
        manual_progress_percent,
        "Manual progress percent",
        errors,
        minimum=0,
        maximum=100,
    )
    if errors:
        error_url = review_return_url_with_error(return_url, errors[0])
        return RedirectResponse(error_url, status_code=status.HTTP_303_SEE_OTHER)

    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)

    old_status = book.status
    old_completed_on = book.completed_on
    old_progress = book.manual_progress_percent
    book.manual_progress_percent = parsed_progress

    correction_event = correction_event_for_changes(
        book,
        old_status=old_status,
        old_completed_on=old_completed_on,
        old_progress=old_progress,
    )
    if correction_event is not None:
        db.add(correction_event)

    db.commit()
    return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{book_id}/review/completion-date")
async def update_review_book_completion_date(
    book_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    completed_on: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
) -> Response:
    return_url = safe_review_return_url(return_to)
    errors: list[str] = []
    parsed_completed_on = parse_optional_date(completed_on, "Completed date", errors)
    if errors:
        error_url = review_return_url_with_error(return_url, errors[0])
        return RedirectResponse(error_url, status_code=status.HTTP_303_SEE_OTHER)

    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)

    old_status = book.status
    old_completed_on = book.completed_on
    old_progress = book.manual_progress_percent
    book.completed_on = parsed_completed_on

    correction_event = correction_event_for_changes(
        book,
        old_status=old_status,
        old_completed_on=old_completed_on,
        old_progress=old_progress,
    )
    if correction_event is not None:
        db.add(correction_event)

    db.commit()
    return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{book_id}/review/archive")
async def archive_review_book(
    book_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    return_to: str | None = Form(default=None),
) -> Response:
    return_url = safe_review_return_url(return_to)
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)

    if book.archived_at is None:
        book.archived_at = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{book_id}/review/restore")
async def restore_review_book(
    book_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    return_to: str | None = Form(default=None),
) -> Response:
    return_url = safe_review_return_url(return_to)
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)

    if book.archived_at is not None:
        book.archived_at = None
        db.commit()
    return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{book_id}/review/state")
async def update_review_book_state(
    book_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    review_status: str = Form(...),
    return_to: str | None = Form(default=None),
) -> Response:
    return_url = safe_review_return_url(return_to)
    if review_status not in {"reviewed", "ignored"}:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)

    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)

    book.review_status = review_status
    book.reviewed_at = datetime.now(timezone.utc)
    book.review_note = f"Marked {review_status} from import review."
    db.commit()
    return RedirectResponse(return_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/new", response_class=HTMLResponse)
async def new_book_form(
    request: Request,
    _: None = Depends(require_write_access),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "books/new.html",
        template_context(
            request,
            page_title="Add Book",
            heading="Add Book",
            description="Create a local book record. Imports and enrichment can fill in more later.",
            form_action="/books/new",
            cancel_href="/books",
            submit_label="Create Book",
            errors=[],
            form={},
            book_statuses=BOOK_STATUSES,
            book_formats=BOOK_FORMATS,
        ),
    )


@router.post("/new")
async def create_book(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    title: str = Form(...),
    subtitle: str | None = Form(default=None),
    primary_author_name: str | None = Form(default=None),
    isbn: str | None = Form(default=None),
    format: str = Form(default="unknown"),
    status_value: str = Form(default="unknown", alias="status"),
    rating: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    started_on: str | None = Form(default=None),
    completed_on: str | None = Form(default=None),
    page_count: str | None = Form(default=None),
    audio_hours: str | None = Form(default=None),
    manual_progress_percent: str | None = Form(default=None),
) -> Response:
    form = submitted_form_values(
        title=title,
        subtitle=subtitle,
        primary_author_name=primary_author_name,
        isbn=isbn,
        format=format,
        status_value=status_value,
        rating=rating,
        notes=notes,
        started_on=started_on,
        completed_on=completed_on,
        page_count=page_count,
        audio_hours=audio_hours,
        manual_progress_percent=manual_progress_percent,
    )
    errors: list[str] = []
    clean_title = clean_optional(title)
    if clean_title is None:
        errors.append("Title is required.")
    if format not in BOOK_FORMATS:
        errors.append("Format is invalid.")
    if status_value not in BOOK_STATUSES:
        errors.append("Status is invalid.")

    parsed_rating = parse_optional_float(rating, "Rating", errors, minimum=0, maximum=5)
    parsed_started_on = parse_optional_date(started_on, "Started date", errors)
    parsed_completed_on = parse_optional_date(completed_on, "Completed date", errors)
    parsed_page_count = parse_optional_int(page_count, "Page count", errors, minimum=1)
    parsed_audio_hours = parse_optional_float(audio_hours, "Audio duration", errors, minimum=0)
    parsed_isbn10, parsed_isbn13 = parse_optional_isbn(isbn, errors)
    parsed_progress = parse_optional_float(
        manual_progress_percent,
        "Manual progress percent",
        errors,
        minimum=0,
        maximum=100,
    )

    if parsed_started_on and parsed_completed_on and parsed_completed_on < parsed_started_on:
        errors.append("Completed date cannot be before started date.")

    if errors:
        return templates.TemplateResponse(
            request,
            "books/new.html",
            template_context(
                request,
                page_title="Add Book",
                heading="Add Book",
                description="Create a local book record. Imports and enrichment can fill in more later.",
                form_action="/books/new",
                cancel_href="/books",
                submit_label="Create Book",
                errors=errors,
                form=form,
                book_statuses=BOOK_STATUSES,
                book_formats=BOOK_FORMATS,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=clean_title or "",
        subtitle=clean_optional(subtitle),
        primary_author_name=clean_optional(primary_author_name),
        isbn10=parsed_isbn10,
        isbn13=parsed_isbn13,
        format=format,
        status=status_value,
        rating=parsed_rating,
        notes=clean_optional(notes),
        started_on=parsed_started_on,
        completed_on=parsed_completed_on,
        page_count=parsed_page_count,
        audio_seconds=round(parsed_audio_hours * 3600) if parsed_audio_hours is not None else None,
        manual_progress_percent=parsed_progress,
        title_source="manual",
        author_source="manual" if clean_optional(primary_author_name) else None,
        metadata_source="manual",
    )
    db.add(book)
    db.flush()

    for event in build_initial_events(book):
        db.add(event)

    db.commit()
    return RedirectResponse(f"/books/{book.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{book_id}/edit", response_class=HTMLResponse)
async def edit_book_form(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> HTMLResponse:
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return templates.TemplateResponse(
        request,
        "books/new.html",
        template_context(
            request,
            page_title="Edit Book",
            heading="Edit Book",
            description="Update this local book record without deleting its reading event history.",
            form_action=f"/books/{book.id}/edit",
            cancel_href=f"/books/{book.id}",
            submit_label="Save Changes",
            errors=[],
            form=book_form_values(book),
            book_statuses=BOOK_STATUSES,
            book_formats=BOOK_FORMATS,
        ),
    )


@router.post("/{book_id}/edit")
async def update_book(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    title: str = Form(...),
    subtitle: str | None = Form(default=None),
    primary_author_name: str | None = Form(default=None),
    isbn: str | None = Form(default=None),
    format: str = Form(default="unknown"),
    status_value: str = Form(default="unknown", alias="status"),
    rating: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    started_on: str | None = Form(default=None),
    completed_on: str | None = Form(default=None),
    page_count: str | None = Form(default=None),
    audio_hours: str | None = Form(default=None),
    manual_progress_percent: str | None = Form(default=None),
) -> Response:
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    form = submitted_form_values(
        title=title,
        subtitle=subtitle,
        primary_author_name=primary_author_name,
        isbn=isbn,
        format=format,
        status_value=status_value,
        rating=rating,
        notes=notes,
        started_on=started_on,
        completed_on=completed_on,
        page_count=page_count,
        audio_hours=audio_hours,
        manual_progress_percent=manual_progress_percent,
    )
    errors: list[str] = []
    clean_title = clean_optional(title)
    if clean_title is None:
        errors.append("Title is required.")
    if format not in BOOK_FORMATS:
        errors.append("Format is invalid.")
    if status_value not in BOOK_STATUSES:
        errors.append("Status is invalid.")

    parsed_rating = parse_optional_float(rating, "Rating", errors, minimum=0, maximum=5)
    parsed_started_on = parse_optional_date(started_on, "Started date", errors)
    parsed_completed_on = parse_optional_date(completed_on, "Completed date", errors)
    parsed_page_count = parse_optional_int(page_count, "Page count", errors, minimum=1)
    parsed_audio_hours = parse_optional_float(audio_hours, "Audio duration", errors, minimum=0)
    parsed_isbn10, parsed_isbn13 = parse_optional_isbn(isbn, errors)
    parsed_progress = parse_optional_float(
        manual_progress_percent,
        "Manual progress percent",
        errors,
        minimum=0,
        maximum=100,
    )
    if parsed_started_on and parsed_completed_on and parsed_completed_on < parsed_started_on:
        errors.append("Completed date cannot be before started date.")

    if errors:
        return templates.TemplateResponse(
            request,
            "books/new.html",
            template_context(
                request,
                page_title="Edit Book",
                heading="Edit Book",
                description="Update this local book record without deleting its reading event history.",
                form_action=f"/books/{book.id}/edit",
                cancel_href=f"/books/{book.id}",
                submit_label="Save Changes",
                errors=errors,
                form=form,
                book_statuses=BOOK_STATUSES,
                book_formats=BOOK_FORMATS,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    old_status = book.status
    old_completed_on = book.completed_on
    old_progress = book.manual_progress_percent

    book.title = clean_title or ""
    book.subtitle = clean_optional(subtitle)
    book.primary_author_name = clean_optional(primary_author_name)
    book.isbn10 = parsed_isbn10
    book.isbn13 = parsed_isbn13
    book.format = format
    book.status = status_value
    book.rating = parsed_rating
    book.notes = clean_optional(notes)
    book.started_on = parsed_started_on
    book.completed_on = parsed_completed_on
    book.page_count = parsed_page_count
    book.audio_seconds = round(parsed_audio_hours * 3600) if parsed_audio_hours is not None else None
    book.manual_progress_percent = parsed_progress
    book.title_source = "manual"
    book.author_source = "manual" if clean_optional(primary_author_name) else None
    book.metadata_source = "manual"

    correction_event = correction_event_for_changes(
        book,
        old_status=old_status,
        old_completed_on=old_completed_on,
        old_progress=old_progress,
    )
    if correction_event is not None:
        db.add(correction_event)

    db.commit()
    return RedirectResponse(f"/books/{book.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{book_id}/archive")
async def archive_book(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> Response:
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if book.archived_at is None:
        book.archived_at = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(f"/books/{book.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{book_id}/restore")
async def restore_book(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> Response:
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if book.archived_at is not None:
        book.archived_at = None
        db.commit()
    return RedirectResponse(f"/books/{book.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{book_id}", response_class=HTMLResponse)
async def book_detail(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    book = db.scalars(
        select(Book)
        .options(joinedload(Book.progress))
        .where(Book.id == book_id, Book.user_id == DEFAULT_LOCAL_USER_ID)
    ).first()
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    events = db.scalars(
        select(ReadingEvent)
        .where(ReadingEvent.book_id == book.id, ReadingEvent.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(ReadingEvent.event_date.desc(), ReadingEvent.id.desc())
    ).all()

    return templates.TemplateResponse(
        request,
        "books/detail.html",
        template_context(
            request,
            page_title=book.title,
            book=book,
            events=events,
            progress_percent=display_progress(book),
            audio_duration=format_audio_seconds(book.audio_seconds),
        ),
    )
