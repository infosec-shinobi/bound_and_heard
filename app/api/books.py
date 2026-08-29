from datetime import date, datetime, time, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import Book, BookProgress, LibbySeriesHint, MetadataEnrichmentRun, ReadingEvent, Series, SeriesBook
from app.services.metadata_apply import apply_metadata_result_to_empty_fields
from app.services.metadata_lookup import MetadataCandidate, lookup_book_metadata
from app.services.metadata_providers import GoogleBooksClient, MetadataProvider, OpenLibraryClient


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


def get_metadata_providers(settings: Settings = Depends(get_settings)) -> list[MetadataProvider]:
    return [OpenLibraryClient(), GoogleBooksClient(api_key=settings.google_books_api_key)]


def new_book_template_context(
    request: Request,
    *,
    errors: list[str] | None = None,
    form: dict[str, str] | None = None,
    message: str | None = None,
) -> dict[str, object]:
    return template_context(
        request,
        page_title="Add Book",
        heading="Add Book",
        description="Create a local book record. Lookup can prefill metadata before you save.",
        form_action="/books/new",
        lookup_action="/books/new/lookup",
        cancel_href="/books",
        submit_label="Create Book",
        errors=errors or [],
        form=form or {},
        message=message,
        book_statuses=BOOK_STATUSES,
        book_formats=BOOK_FORMATS,
        show_lookup=True,
    )


def clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def provider_label(value: str) -> str:
    return value.replace("_", " ").title()


def normalize_duplicate_text(value: str | None) -> str | None:
    value = clean_optional(value)
    if value is None:
        return None
    return WHITESPACE_PATTERN.sub(" ", value.casefold())


def normalize_series_name(value: str | None) -> str:
    return WHITESPACE_PATTERN.sub(" ", (value or "").strip().casefold())


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


def parse_optional_series_position(value: str | None, errors: list[str]) -> float | None:
    value = clean_optional(value)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        errors.append("Series position must be a number.")
        return None


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


def format_enjoyed_seconds(enjoyed_seconds: int | None) -> str | None:
    return format_audio_seconds(enjoyed_seconds)


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
    query_items = [
        (key, item_value)
        for key, item_value in parse_qsl(parsed.query)
        if key not in {"review_error", "review_message"}
    ]
    return urlunsplit(("", "", parsed.path, urlencode(query_items), ""))


def review_return_url_with_error(return_url: str, message: str) -> str:
    parsed = urlsplit(return_url)
    query_items = parse_qsl(parsed.query)
    query_items.append(("review_error", message))
    return urlunsplit(("", "", parsed.path, urlencode(query_items), ""))


def review_return_url_with_message(return_url: str, message: str) -> str:
    parsed = urlsplit(return_url)
    query_items = parse_qsl(parsed.query)
    query_items.append(("review_message", message))
    return urlunsplit(("", "", parsed.path, urlencode(query_items), ""))


def book_detail_redirect(book_id: int, **params: str) -> RedirectResponse:
    query = urlencode(params)
    target = f"/books/{book_id}"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def is_prior_completion_event(event: ReadingEvent) -> bool:
    raw_data = event.raw_data if isinstance(event.raw_data, dict) else {}
    return event.source == "manual" and event.event_type == "manually_completed" and raw_data.get("prior_entry") is True


def enrichment_message_for_status(enrichment_status: str, applied_fields: list[str] | None = None) -> str:
    if enrichment_status == "matched":
        if applied_fields:
            return "Metadata enriched: " + ", ".join(applied_fields) + "."
        return "Metadata provider matched, but no empty supported fields needed updates."
    if enrichment_status == "ambiguous":
        return "Metadata enrichment found ambiguous matches. Review candidates before applying changes."
    if enrichment_status == "low_confidence":
        return "Metadata enrichment found only low-confidence matches, so nothing was applied."
    if enrichment_status == "no_candidates":
        return "No useful metadata enrichment candidates were found."
    return "Metadata enrichment could not be completed."


def lookup_attempt_summary(attempts: object) -> str:
    parts = []
    for attempt in attempts:
        provider = provider_label(attempt.provider)
        status_label = attempt.status.replace("_", " ")
        if attempt.status == "failed" and attempt.http_status in {500, 502, 503, 504}:
            status_label = "temporarily unavailable"
        detail = f"{provider}: {status_label}"
        if attempt.http_status is not None:
            detail = f"{detail} ({attempt.http_status})"
        parts.append(detail)
    return "; ".join(parts)


def enrichment_message_with_attempts(enrichment_status: str, attempts: object) -> str:
    message = enrichment_message_for_status(enrichment_status)
    summary = lookup_attempt_summary(attempts)
    return f"{message} Tried {summary}." if summary else message


def bulk_enrichment_summary_message(summary: dict[str, int]) -> str:
    return (
        "Bulk enrichment checked {checked} book(s): {updated} updated, {skipped} skipped, "
        "{ambiguous} ambiguous, {low_confidence} low confidence, {errors} error(s)."
    ).format(**summary)


def book_detail_response(
    request: Request,
    db: Session,
    book: Book,
    *,
    message: str | None = None,
    enrichment_status: str | None = None,
    enrichment_candidates: tuple[MetadataCandidate, ...] = (),
) -> HTMLResponse:
    events = db.scalars(
        select(ReadingEvent)
        .where(ReadingEvent.book_id == book.id, ReadingEvent.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(ReadingEvent.event_date.desc(), ReadingEvent.id.desc())
    ).all()
    series_entries = db.scalars(
        select(SeriesBook)
        .join(Series)
        .options(joinedload(SeriesBook.series))
        .where(SeriesBook.book_id == book.id, Series.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(Series.name.asc())
    ).all()
    assigned_series_ids = {entry.series_id for entry in series_entries}
    available_series = db.scalars(
        select(Series)
        .where(Series.user_id == DEFAULT_LOCAL_USER_ID, Series.id.not_in(assigned_series_ids))
        .order_by(Series.name.asc())
    ).all()
    enrichment_runs = db.scalars(
        select(MetadataEnrichmentRun)
        .where(MetadataEnrichmentRun.book_id == book.id, MetadataEnrichmentRun.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(MetadataEnrichmentRun.created_at.desc(), MetadataEnrichmentRun.id.desc())
        .limit(5)
    ).all()
    libby_series_hints = db.scalars(
        select(LibbySeriesHint)
        .where(LibbySeriesHint.book_id == book.id, LibbySeriesHint.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(LibbySeriesHint.created_at.desc(), LibbySeriesHint.id.desc())
    ).all()
    prior_event_ids = {event.id for event in events if is_prior_completion_event(event)}

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
            enjoyed_duration=format_enjoyed_seconds(book.progress.enjoyed_seconds if book.progress else None),
            current_position_duration=format_audio_seconds(book.progress.position_seconds if book.progress else None),
            series_entries=series_entries,
            available_series=available_series,
            message=message,
            enrichment_status=enrichment_status,
            enrichment_runs=enrichment_runs,
            enrichment_candidates=enrichment_candidates,
            libby_series_hints=libby_series_hints,
            prior_event_ids=prior_event_ids,
        ),
    )


def active_review_filter_labels(active_filters: dict[str, bool]) -> list[str]:
    filter_labels = REVIEW_METADATA_FILTERS | REVIEW_SUSPICIOUS_FILTERS
    return [filter_labels[name] for name, is_active in active_filters.items() if is_active and name in filter_labels]


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
        "publisher": book.publisher or "",
        "published_on": book.published_on.isoformat() if book.published_on else "",
        "publication_year": str(book.publication_year) if book.publication_year is not None else "",
        "format": book.format,
        "status": book.status,
        "rating": f"{book.rating:g}" if book.rating is not None else "",
        "notes": book.notes or "",
        "started_on": book.started_on.isoformat() if book.started_on else "",
        "completed_on": book.completed_on.isoformat() if book.completed_on else "",
        "page_count": str(book.page_count) if book.page_count is not None else "",
        "audio_hours": audio_seconds_to_hours(book.audio_seconds),
        "cover_url": book.cover_url or "",
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
    publisher: str | None,
    published_on: str | None,
    publication_year: str | None,
    format: str,
    status_value: str,
    rating: str | None,
    notes: str | None,
    started_on: str | None,
    completed_on: str | None,
    page_count: str | None,
    audio_hours: str | None,
    cover_url: str | None,
    manual_progress_percent: str | None,
) -> dict[str, str]:
    return {
        "title": title,
        "subtitle": subtitle or "",
        "primary_author_name": primary_author_name or "",
        "isbn": isbn or "",
        "publisher": publisher or "",
        "published_on": published_on or "",
        "publication_year": publication_year or "",
        "format": format,
        "status": status_value,
        "rating": rating or "",
        "notes": notes or "",
        "started_on": started_on or "",
        "completed_on": completed_on or "",
        "page_count": page_count or "",
        "audio_hours": audio_hours or "",
        "cover_url": cover_url or "",
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


def review_active_filters(
    *,
    missing_page_count: bool,
    missing_audio_duration: bool,
    missing_author: bool,
    missing_publisher: bool,
    missing_isbn: bool,
    missing_cover_url: bool,
    unknown_format: bool,
    unknown_status: bool,
    missing_libby_title_id: bool,
    fallback_title: bool,
    no_reading_events: bool,
    completed_without_completion_date: bool,
    progress_status_mismatch: bool,
    duplicate_candidate: bool,
) -> dict[str, bool]:
    return {
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


def duplicate_reasons_for_review(db: Session) -> dict[int, list[str]]:
    duplicate_universe = db.scalars(
        select(Book).where(
            Book.user_id == DEFAULT_LOCAL_USER_ID,
            Book.archived_at.is_(None),
        )
    ).all()
    return duplicate_reasons_by_book_id(list(duplicate_universe))


def review_books_statement(
    *,
    active_filters: dict[str, bool],
    duplicate_reasons: dict[int, list[str]],
) -> Select[tuple[Book]]:
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

    if active_filters["missing_page_count"]:
        statement = statement.where(Book.page_count.is_(None))
    if active_filters["missing_audio_duration"]:
        statement = statement.where(Book.audio_seconds.is_(None))
    if active_filters["missing_author"]:
        statement = statement.where(missing_text_filter(Book.primary_author_name))
    if active_filters["missing_publisher"]:
        statement = statement.where(missing_text_filter(Book.publisher))
    if active_filters["missing_isbn"]:
        statement = statement.where(missing_text_filter(Book.isbn10), missing_text_filter(Book.isbn13))
    if active_filters["missing_cover_url"]:
        statement = statement.where(missing_text_filter(Book.cover_url))
    if active_filters["unknown_format"]:
        statement = statement.where(Book.format == "unknown")
    if active_filters["unknown_status"]:
        statement = statement.where(Book.status == "unknown")
    if active_filters["missing_libby_title_id"]:
        statement = statement.where(missing_text_filter(Book.libby_title_id))
    if active_filters["fallback_title"]:
        statement = statement.where(func.lower(func.trim(Book.title)).in_(TITLE_FALLBACK_VALUES))
    if active_filters["no_reading_events"]:
        statement = statement.where(~Book.reading_events.any())
    if active_filters["completed_without_completion_date"]:
        statement = statement.where(Book.status == "completed", Book.completed_on.is_(None))
    if active_filters["progress_status_mismatch"]:
        progress = review_progress_expression()
        statement = statement.where(
            or_(
                and_(Book.status == "completed", progress.is_not(None), progress < 100),
                and_(Book.status != "completed", progress >= 100),
            )
        )
    if active_filters["duplicate_candidate"]:
        duplicate_book_ids = list(duplicate_reasons)
        if duplicate_book_ids:
            statement = statement.where(Book.id.in_(duplicate_book_ids))
        else:
            statement = statement.where(Book.id == -1)
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
    enrichment_runs_by_book_id: dict[int, MetadataEnrichmentRun] = {}
    libby_series_hints_by_book_id: dict[int, LibbySeriesHint] = {}
    book_ids = [book.id for book in books]
    if book_ids:
        enrichment_runs = db.scalars(
            select(MetadataEnrichmentRun)
            .where(
                MetadataEnrichmentRun.book_id.in_(book_ids),
                MetadataEnrichmentRun.user_id == DEFAULT_LOCAL_USER_ID,
            )
            .order_by(MetadataEnrichmentRun.created_at.desc(), MetadataEnrichmentRun.id.desc())
        ).all()
        for run in enrichment_runs:
            if run.book_id is not None and run.book_id not in enrichment_runs_by_book_id:
                enrichment_runs_by_book_id[run.book_id] = run
        libby_series_hints = db.scalars(
            select(LibbySeriesHint)
            .where(
                LibbySeriesHint.book_id.in_(book_ids),
                LibbySeriesHint.user_id == DEFAULT_LOCAL_USER_ID,
            )
            .order_by(LibbySeriesHint.created_at.desc(), LibbySeriesHint.id.desc())
        ).all()
        for hint in libby_series_hints:
            if hint.book_id not in libby_series_hints_by_book_id:
                libby_series_hints_by_book_id[hint.book_id] = hint

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
    review_message: str | None = Query(default=None),
) -> HTMLResponse:
    active_filters = review_active_filters(
        missing_page_count=missing_page_count,
        missing_audio_duration=missing_audio_duration,
        missing_author=missing_author,
        missing_publisher=missing_publisher,
        missing_isbn=missing_isbn,
        missing_cover_url=missing_cover_url,
        unknown_format=unknown_format,
        unknown_status=unknown_status,
        missing_libby_title_id=missing_libby_title_id,
        fallback_title=fallback_title,
        no_reading_events=no_reading_events,
        completed_without_completion_date=completed_without_completion_date,
        progress_status_mismatch=progress_status_mismatch,
        duplicate_candidate=duplicate_candidate,
    )
    duplicate_reasons = duplicate_reasons_for_review(db)
    statement = review_books_statement(active_filters=active_filters, duplicate_reasons=duplicate_reasons)

    books = db.scalars(statement).unique().all()
    enrichment_runs_by_book_id: dict[int, MetadataEnrichmentRun] = {}
    libby_series_hints_by_book_id: dict[int, LibbySeriesHint] = {}
    book_ids = [book.id for book in books]
    if book_ids:
        enrichment_runs = db.scalars(
            select(MetadataEnrichmentRun)
            .where(
                MetadataEnrichmentRun.book_id.in_(book_ids),
                MetadataEnrichmentRun.user_id == DEFAULT_LOCAL_USER_ID,
            )
            .order_by(MetadataEnrichmentRun.created_at.desc(), MetadataEnrichmentRun.id.desc())
        ).all()
        for run in enrichment_runs:
            if run.book_id is not None and run.book_id not in enrichment_runs_by_book_id:
                enrichment_runs_by_book_id[run.book_id] = run
        libby_series_hints = db.scalars(
            select(LibbySeriesHint)
            .where(
                LibbySeriesHint.book_id.in_(book_ids),
                LibbySeriesHint.user_id == DEFAULT_LOCAL_USER_ID,
            )
            .order_by(LibbySeriesHint.created_at.desc(), LibbySeriesHint.id.desc())
        ).all()
        for hint in libby_series_hints:
            if hint.book_id not in libby_series_hints_by_book_id:
                libby_series_hints_by_book_id[hint.book_id] = hint

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
            active_filter_labels=active_review_filter_labels(active_filters),
            book_statuses=BOOK_STATUSES,
            review_error=review_error,
            review_message=review_message,
            duplicate_reasons=duplicate_reasons,
            enrichment_runs_by_book_id=enrichment_runs_by_book_id,
            libby_series_hints_by_book_id=libby_series_hints_by_book_id,
            format_audio_seconds=format_audio_seconds,
        ),
    )


@router.post("/review/enrich")
async def bulk_enrich_review_books(
    db: Session = Depends(get_db),
    providers: list[MetadataProvider] = Depends(get_metadata_providers),
    _: None = Depends(require_write_access),
    book_ids: list[int] = Form(default=[]),
    return_to: str | None = Form(default=None),
    missing_page_count: bool = Form(default=False),
    missing_audio_duration: bool = Form(default=False),
    missing_author: bool = Form(default=False),
    missing_publisher: bool = Form(default=False),
    missing_isbn: bool = Form(default=False),
    missing_cover_url: bool = Form(default=False),
    unknown_format: bool = Form(default=False),
    unknown_status: bool = Form(default=False),
    missing_libby_title_id: bool = Form(default=False),
    fallback_title: bool = Form(default=False),
    no_reading_events: bool = Form(default=False),
    completed_without_completion_date: bool = Form(default=False),
    progress_status_mismatch: bool = Form(default=False),
    duplicate_candidate: bool = Form(default=False),
) -> Response:
    return_url = safe_review_return_url(return_to)
    active_filters = review_active_filters(
        missing_page_count=missing_page_count,
        missing_audio_duration=missing_audio_duration,
        missing_author=missing_author,
        missing_publisher=missing_publisher,
        missing_isbn=missing_isbn,
        missing_cover_url=missing_cover_url,
        unknown_format=unknown_format,
        unknown_status=unknown_status,
        missing_libby_title_id=missing_libby_title_id,
        fallback_title=fallback_title,
        no_reading_events=no_reading_events,
        completed_without_completion_date=completed_without_completion_date,
        progress_status_mismatch=progress_status_mismatch,
        duplicate_candidate=duplicate_candidate,
    )
    duplicate_reasons = duplicate_reasons_for_review(db)
    statement = review_books_statement(active_filters=active_filters, duplicate_reasons=duplicate_reasons)
    if book_ids:
        statement = statement.where(Book.id.in_(book_ids))
    books = db.scalars(statement).unique().all()

    summary = {
        "checked": len(books),
        "updated": 0,
        "skipped": 0,
        "ambiguous": 0,
        "low_confidence": 0,
        "errors": 0,
    }
    for book in books:
        outcome = lookup_book_metadata(db, book=book, providers=providers)
        if outcome.status == "matched" and outcome.best_candidate is not None:
            candidate = outcome.best_candidate
            applied = apply_metadata_result_to_empty_fields(
                db,
                book=book,
                result=candidate.result,
                cache_entry_id=candidate.cache_entry.id,
                lookup_type=candidate.response.lookup_type,
                normalized_query=candidate.response.normalized_query,
            )
            if applied.updated:
                summary["updated"] += 1
            else:
                summary["skipped"] += 1
        elif outcome.status == "ambiguous":
            summary["ambiguous"] += 1
        elif outcome.status == "low_confidence":
            summary["low_confidence"] += 1
        elif any(response.status in {"failed", "malformed", "rate_limited"} for response in outcome.attempted_lookups):
            summary["errors"] += 1
        else:
            summary["skipped"] += 1

    db.commit()
    return RedirectResponse(
        review_return_url_with_message(return_url, bulk_enrichment_summary_message(summary)),
        status_code=status.HTTP_303_SEE_OTHER,
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
    return RedirectResponse(
        review_return_url_with_message(return_url, "Status updated."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    return RedirectResponse(
        review_return_url_with_message(return_url, "Manual progress updated."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    return RedirectResponse(
        review_return_url_with_message(return_url, "Completion date updated."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    return RedirectResponse(
        review_return_url_with_message(return_url, "Book archived."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    return RedirectResponse(
        review_return_url_with_message(return_url, "Book restored."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
    return RedirectResponse(
        review_return_url_with_message(return_url, f"Book marked {review_status}."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/new", response_class=HTMLResponse)
async def new_book_form(
    request: Request,
    _: None = Depends(require_write_access),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "books/new.html",
        new_book_template_context(request),
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
    publisher: str | None = Form(default=None),
    published_on: str | None = Form(default=None),
    publication_year: str | None = Form(default=None),
    format: str = Form(default="unknown"),
    status_value: str = Form(default="unknown", alias="status"),
    rating: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    started_on: str | None = Form(default=None),
    completed_on: str | None = Form(default=None),
    page_count: str | None = Form(default=None),
    audio_hours: str | None = Form(default=None),
    cover_url: str | None = Form(default=None),
    manual_progress_percent: str | None = Form(default=None),
) -> Response:
    form = submitted_form_values(
        title=title,
        subtitle=subtitle,
        primary_author_name=primary_author_name,
        isbn=isbn,
        publisher=publisher,
        published_on=published_on,
        publication_year=publication_year,
        format=format,
        status_value=status_value,
        rating=rating,
        notes=notes,
        started_on=started_on,
        completed_on=completed_on,
        page_count=page_count,
        audio_hours=audio_hours,
        cover_url=cover_url,
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
    parsed_published_on = parse_optional_date(published_on, "Published date", errors)
    parsed_publication_year = parse_optional_int(publication_year, "Publication year", errors, minimum=1)
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
            new_book_template_context(request, errors=errors, form=form),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=clean_title or "",
        subtitle=clean_optional(subtitle),
        primary_author_name=clean_optional(primary_author_name),
        isbn10=parsed_isbn10,
        isbn13=parsed_isbn13,
        publisher=clean_optional(publisher),
        published_on=parsed_published_on,
        publication_year=parsed_publication_year,
        format=format,
        status=status_value,
        rating=parsed_rating,
        notes=clean_optional(notes),
        started_on=parsed_started_on,
        completed_on=parsed_completed_on,
        page_count=parsed_page_count,
        audio_seconds=round(parsed_audio_hours * 3600) if parsed_audio_hours is not None else None,
        cover_url=clean_optional(cover_url),
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


@router.post("/new/lookup", response_class=HTMLResponse)
async def lookup_new_book_metadata(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    providers: list[MetadataProvider] = Depends(get_metadata_providers),
    title: str = Form(default=""),
    subtitle: str | None = Form(default=None),
    primary_author_name: str | None = Form(default=None),
    isbn: str | None = Form(default=None),
    publisher: str | None = Form(default=None),
    published_on: str | None = Form(default=None),
    publication_year: str | None = Form(default=None),
    format: str = Form(default="unknown"),
    status_value: str = Form(default="unknown", alias="status"),
    rating: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    started_on: str | None = Form(default=None),
    completed_on: str | None = Form(default=None),
    page_count: str | None = Form(default=None),
    audio_hours: str | None = Form(default=None),
    cover_url: str | None = Form(default=None),
    manual_progress_percent: str | None = Form(default=None),
    force_refresh: bool = Form(default=False),
) -> HTMLResponse:
    form = submitted_form_values(
        title=title,
        subtitle=subtitle,
        primary_author_name=primary_author_name,
        isbn=isbn,
        publisher=publisher,
        published_on=published_on,
        publication_year=publication_year,
        format=format,
        status_value=status_value,
        rating=rating,
        notes=notes,
        started_on=started_on,
        completed_on=completed_on,
        page_count=page_count,
        audio_hours=audio_hours,
        cover_url=cover_url,
        manual_progress_percent=manual_progress_percent,
    )
    errors: list[str] = []
    parsed_isbn10, parsed_isbn13 = parse_optional_isbn(isbn, errors)
    normalized_isbn = parsed_isbn13 or parsed_isbn10
    if normalized_isbn is not None:
        form["isbn"] = normalized_isbn
    if not clean_optional(isbn):
        errors.append("ISBN is required for lookup.")
    if errors:
        return templates.TemplateResponse(
            request,
            "books/new.html",
            new_book_template_context(request, errors=errors, form=form),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    lookup_book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title="",
        subtitle=clean_optional(subtitle),
        primary_author_name=clean_optional(primary_author_name),
        isbn10=parsed_isbn10,
        isbn13=parsed_isbn13,
        format=format if format in BOOK_FORMATS else "unknown",
        status=status_value if status_value in BOOK_STATUSES else "unknown",
    )
    outcome = lookup_book_metadata(db, book=lookup_book, providers=providers, force_refresh=force_refresh)
    candidate = outcome.best_candidate
    if candidate is None or outcome.status != "matched":
        message = enrichment_message_with_attempts(outcome.status, outcome.attempted_lookups)
        return templates.TemplateResponse(
            request,
            "books/new.html",
            new_book_template_context(request, form=form, message=message),
            status_code=status.HTTP_200_OK,
        )

    result = candidate.result
    if not clean_optional(form["title"]):
        form["title"] = result.title
    if not clean_optional(form["subtitle"]):
        form["subtitle"] = result.subtitle or ""
    if not clean_optional(form["primary_author_name"]):
        form["primary_author_name"] = result.authors[0] if result.authors else ""
    if not clean_optional(form["isbn"]):
        form["isbn"] = result.isbn13 or result.isbn10 or ""
    if not clean_optional(form["publisher"]):
        form["publisher"] = result.publisher or ""
    if not clean_optional(form["published_on"]):
        form["published_on"] = result.published_on.isoformat() if result.published_on else ""
    if not clean_optional(form["publication_year"]):
        form["publication_year"] = str(result.publication_year) if result.publication_year is not None else ""
    if not clean_optional(form["page_count"]):
        form["page_count"] = str(result.page_count) if result.page_count is not None else ""
    if not clean_optional(form["cover_url"]):
        form["cover_url"] = result.cover_url or ""

    message = f"Found metadata from {provider_label(result.provider)}. Review the prefilled fields, then create the book."
    return templates.TemplateResponse(
        request,
        "books/new.html",
        new_book_template_context(request, form=form, message=message),
    )


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
    publisher: str | None = Form(default=None),
    published_on: str | None = Form(default=None),
    publication_year: str | None = Form(default=None),
    format: str = Form(default="unknown"),
    status_value: str = Form(default="unknown", alias="status"),
    rating: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    started_on: str | None = Form(default=None),
    completed_on: str | None = Form(default=None),
    page_count: str | None = Form(default=None),
    audio_hours: str | None = Form(default=None),
    cover_url: str | None = Form(default=None),
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
        publisher=publisher,
        published_on=published_on,
        publication_year=publication_year,
        format=format,
        status_value=status_value,
        rating=rating,
        notes=notes,
        started_on=started_on,
        completed_on=completed_on,
        page_count=page_count,
        audio_hours=audio_hours,
        cover_url=cover_url,
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
    parsed_published_on = parse_optional_date(published_on, "Published date", errors)
    parsed_publication_year = parse_optional_int(publication_year, "Publication year", errors, minimum=1)
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
    book.publisher = clean_optional(publisher)
    book.published_on = parsed_published_on
    book.publication_year = parsed_publication_year
    book.format = format
    book.status = status_value
    book.rating = parsed_rating
    book.notes = clean_optional(notes)
    book.started_on = parsed_started_on
    book.completed_on = parsed_completed_on
    book.page_count = parsed_page_count
    book.audio_seconds = round(parsed_audio_hours * 3600) if parsed_audio_hours is not None else None
    book.cover_url = clean_optional(cover_url)
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


@router.post("/{book_id}/scraped-progress/clear")
async def clear_book_scraped_progress(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> Response:
    book = db.scalars(
        select(Book)
        .options(joinedload(Book.progress))
        .where(Book.id == book_id, Book.user_id == DEFAULT_LOCAL_USER_ID)
    ).first()
    if book is None:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    cleared = False
    if book.progress is not None and book.progress.source == "scraped":
        db.delete(book.progress)
        cleared = True
    result = db.execute(
        delete(ReadingEvent).where(
            ReadingEvent.book_id == book.id,
            ReadingEvent.user_id == DEFAULT_LOCAL_USER_ID,
            ReadingEvent.source == "scraped",
        )
    )
    cleared = cleared or bool(result.rowcount)
    db.commit()
    message = "Scraped progress cleared." if cleared else "No scraped progress found to clear."
    return RedirectResponse(
        f"/books/{book.id}?{urlencode({'message': message})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{book_id}/prior-completions")
async def add_prior_completion(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    completed_on: str | None = Form(default=None),
) -> Response:
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    errors: list[str] = []
    parsed_completed_on = parse_optional_date(completed_on, "Prior completion date", errors)
    if parsed_completed_on is None:
        errors.append("Prior completion date is required.")
    if errors:
        return book_detail_redirect(book.id, message=errors[0])

    event = ReadingEvent(
        user_id=book.user_id,
        book_id=book.id,
        source="manual",
        source_event_id=f"manual_prior:{book.id}:{parsed_completed_on.isoformat()}:{uuid4().hex}",
        event_type="manually_completed",
        event_date=date_to_datetime(parsed_completed_on),
        progress_percent=100,
        raw_data={"prior_entry": True, "entry_method": "book_detail"},
    )
    db.add(event)
    db.commit()
    label = "prior listen" if book.format == "audiobook" else "prior read"
    return book_detail_redirect(book.id, message=f"Added {label} entry for {parsed_completed_on.isoformat()}.")


@router.post("/{book_id}/prior-completions/{event_id}/delete")
async def delete_prior_completion(
    book_id: int,
    event_id: int,
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
    event = db.get(ReadingEvent, event_id)
    if event is None or event.book_id != book.id or event.user_id != DEFAULT_LOCAL_USER_ID or not is_prior_completion_event(event):
        return book_detail_redirect(book.id, message="Prior read/listen entry not found.")

    db.delete(event)
    db.commit()
    return book_detail_redirect(book.id, message="Prior read/listen entry removed.")


@router.post("/{book_id}/series/add")
async def add_book_to_series_from_detail(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
    series_id: int = Form(...),
    position: str | None = Form(default=None),
) -> Response:
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    series = db.get(Series, series_id)
    if series is None or series.user_id != DEFAULT_LOCAL_USER_ID:
        return book_detail_redirect(book.id, message="Series not found.")

    existing = db.scalars(
        select(SeriesBook).where(SeriesBook.series_id == series.id, SeriesBook.book_id == book.id)
    ).first()
    if existing is not None:
        return book_detail_redirect(book.id, message=f"{book.title} is already in {series.name}.")

    errors: list[str] = []
    parsed_position = parse_optional_series_position(position, errors)
    if errors:
        return book_detail_redirect(book.id, message=errors[0])

    db.add(SeriesBook(series_id=series.id, book_id=book.id, position=parsed_position))
    db.commit()
    return book_detail_redirect(book.id, message=f"Added to series: {series.name}")


@router.post("/{book_id}/series-hints/{hint_id}/apply")
async def apply_libby_series_hint_from_detail(
    book_id: int,
    hint_id: int,
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
    hint = db.get(LibbySeriesHint, hint_id)
    if hint is None or hint.book_id != book.id or hint.user_id != DEFAULT_LOCAL_USER_ID:
        return book_detail_redirect(book.id, message="Libby series suggestion not found.")
    if not hint.series_name:
        return book_detail_redirect(book.id, message="Libby series suggestion is missing a series name.")
    existing_assignment = db.scalars(select(SeriesBook).where(SeriesBook.book_id == book.id)).first()
    if existing_assignment is not None:
        return book_detail_redirect(book.id, message="Book already has a series assignment. No Libby suggestion was applied.")

    normalized_hint_name = normalize_series_name(hint.series_name)
    series = None
    for candidate in db.scalars(select(Series).where(Series.user_id == DEFAULT_LOCAL_USER_ID)).all():
        if normalize_series_name(candidate.name) == normalized_hint_name:
            series = candidate
            break
    if series is None:
        series = Series(user_id=DEFAULT_LOCAL_USER_ID, name=hint.series_name, status="unknown", wants_to_continue="unknown")
        db.add(series)
        db.flush()

    db.add(SeriesBook(series_id=series.id, book_id=book.id, position=hint.position))
    hint.status = "applied"
    hint.applied_at = datetime.now(timezone.utc)
    db.commit()
    return book_detail_redirect(book.id, message=f"Applied Libby series suggestion: {hint.raw_label}")


@router.post("/{book_id}/series/{entry_id}/remove")
async def remove_book_from_series_from_detail(
    book_id: int,
    entry_id: int,
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

    entry = db.scalars(
        select(SeriesBook)
        .join(Series)
        .where(
            SeriesBook.id == entry_id,
            SeriesBook.book_id == book.id,
            Series.user_id == DEFAULT_LOCAL_USER_ID,
        )
    ).first()
    if entry is None:
        return book_detail_redirect(book.id, message="Series membership not found.")

    series_name = entry.series.name
    db.delete(entry)
    db.commit()
    return book_detail_redirect(book.id, message=f"Removed from series: {series_name}")


@router.post("/{book_id}/enrich")
async def enrich_book_metadata(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    providers: list[MetadataProvider] = Depends(get_metadata_providers),
    _: None = Depends(require_write_access),
    force_refresh: bool = Form(default=False),
    return_to: str | None = Form(default=None),
) -> Response:
    book = db.get(Book, book_id)
    if book is None or book.user_id != DEFAULT_LOCAL_USER_ID:
        return templates.TemplateResponse(
            request,
            "books/not_found.html",
            template_context(request, page_title="Book Not Found"),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    outcome = lookup_book_metadata(db, book=book, providers=providers, force_refresh=force_refresh)
    applied_fields: list[str] = []
    if outcome.status == "matched" and outcome.best_candidate is not None:
        candidate = outcome.best_candidate
        applied = apply_metadata_result_to_empty_fields(
            db,
            book=book,
            result=candidate.result,
            cache_entry_id=candidate.cache_entry.id,
            lookup_type=candidate.response.lookup_type,
            normalized_query=candidate.response.normalized_query,
        )
        applied_fields = sorted(field for field in applied.fields_applied if field != "metadata_source")

    db.commit()
    if return_to is not None:
        return_url = safe_review_return_url(return_to)
        return RedirectResponse(
            review_return_url_with_message(return_url, enrichment_message_for_status(outcome.status, applied_fields)),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if outcome.status in {"ambiguous", "low_confidence"}:
        return book_detail_response(
            request,
            db,
            book,
            message=enrichment_message_for_status(outcome.status, applied_fields),
            enrichment_status=outcome.status,
            enrichment_candidates=outcome.candidates,
        )
    return book_detail_redirect(
        book.id,
        message=enrichment_message_for_status(outcome.status, applied_fields),
        enrichment_status=outcome.status,
    )


@router.get("/{book_id}", response_class=HTMLResponse)
async def book_detail(
    book_id: int,
    request: Request,
    db: Session = Depends(get_db),
    message: str | None = None,
    enrichment_status: str | None = None,
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

    return book_detail_response(request, db, book, message=message, enrichment_status=enrichment_status)
