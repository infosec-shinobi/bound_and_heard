from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers.libby_json import LibbyTimelineItem, build_libby_source_event_id
from app.models import Book, ReadingEvent


@dataclass(frozen=True)
class LibbyBookResult:
    book: Book
    created: bool
    updated: bool


@dataclass(frozen=True)
class LibbyEventResult:
    event: ReadingEvent
    created: bool


@dataclass(frozen=True)
class LibbyImportSummary:
    books_created: int = 0
    books_updated: int = 0
    events_created: int = 0
    events_skipped: int = 0
    unsupported_events: int = 0
    book_ids: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "books_created": self.books_created,
            "books_updated": self.books_updated,
            "events_created": self.events_created,
            "duplicate_events_skipped": self.events_skipped,
            "unsupported_events": self.unsupported_events,
            "book_ids": list(self.book_ids),
        }


LIBBY_ACTIVITY_EVENT_TYPES = {
    "borrowed": "borrowed",
    "returned": "returned",
    "started": "started",
    "opened": "started",
    "progress": "progress_seen",
    "progress seen": "progress_seen",
    "completed": "completed",
    "finished": "completed",
}


def clean_string(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_match_value(value: str | None) -> str:
    return (value or "").strip().casefold()


def libby_activity_to_event_type(activity: str | None) -> str | None:
    normalized = normalize_match_value(activity).replace("_", " ").replace("-", " ")
    return LIBBY_ACTIVITY_EVENT_TYPES.get(" ".join(normalized.split()))


def isbn_fields(isbn: str | None) -> dict[str, str | None]:
    clean_isbn = clean_string(isbn)
    if clean_isbn is None:
        return {"isbn10": None, "isbn13": None}
    digits = "".join(character for character in clean_isbn if character.isdigit() or character.upper() == "X")
    if len(digits) == 10:
        return {"isbn10": digits, "isbn13": None}
    if len(digits) == 13:
        return {"isbn10": None, "isbn13": digits}
    return {"isbn10": None, "isbn13": None}


def find_libby_book_match(db: Session, *, user_id: int, item: LibbyTimelineItem) -> Book | None:
    title_id = clean_string(item.title.title_id)
    if title_id is not None:
        matched_by_id = db.scalars(
            select(Book).where(Book.user_id == user_id, Book.libby_title_id == title_id)
        ).first()
        if matched_by_id is not None:
            return matched_by_id

    title = clean_string(item.title.text)
    author = clean_string(item.author)
    book_format = clean_string(item.cover.format)
    if title is None or author is None or book_format is None:
        return None

    candidates = db.scalars(
        select(Book).where(
            Book.user_id == user_id,
            Book.libby_title_id.is_(None),
            Book.format == book_format,
        )
    ).all()
    for candidate in candidates:
        if (
            normalize_match_value(candidate.title) == normalize_match_value(title)
            and normalize_match_value(candidate.primary_author_name) == normalize_match_value(author)
        ):
            return candidate
    return None


def fill_empty_book_fields(book: Book, item: LibbyTimelineItem) -> bool:
    updated = False
    isbn_values = isbn_fields(item.isbn)
    field_values: dict[str, str | None] = {
        "primary_author_name": clean_string(item.author),
        "publisher": clean_string(item.publisher),
        "isbn10": isbn_values["isbn10"],
        "isbn13": isbn_values["isbn13"],
        "libby_title_id": clean_string(item.title.title_id),
        "libby_share_url": clean_string(item.title.url),
        "cover_url": clean_string(item.cover.url),
        "cover_color": clean_string(item.cover.color),
    }
    for field_name, value in field_values.items():
        if value is not None and getattr(book, field_name) in (None, ""):
            setattr(book, field_name, value)
            updated = True

    if book.format == "unknown" and clean_string(item.cover.format) is not None:
        book.format = clean_string(item.cover.format) or book.format
        updated = True

    if book.metadata_source is None:
        book.metadata_source = "libby"
        updated = True
    if book.author_source is None and clean_string(item.author) is not None and book.primary_author_name == clean_string(item.author):
        book.author_source = "libby"
        updated = True
    return updated


def create_book_from_libby_item(user_id: int, item: LibbyTimelineItem) -> Book:
    title = clean_string(item.title.text) or clean_string(item.cover.title) or "Untitled Libby Book"
    isbn_values = isbn_fields(item.isbn)
    return Book(
        user_id=user_id,
        title=title,
        primary_author_name=clean_string(item.author),
        isbn10=isbn_values["isbn10"],
        isbn13=isbn_values["isbn13"],
        libby_title_id=clean_string(item.title.title_id),
        libby_share_url=clean_string(item.title.url),
        publisher=clean_string(item.publisher),
        format=clean_string(item.cover.format) or "unknown",
        status="borrowed" if item.activity == "Borrowed" else "unknown",
        cover_url=clean_string(item.cover.url),
        cover_color=clean_string(item.cover.color),
        title_source="libby",
        author_source="libby" if clean_string(item.author) else None,
        metadata_source="libby",
    )


def upsert_libby_book(db: Session, *, user_id: int, item: LibbyTimelineItem) -> LibbyBookResult:
    book = find_libby_book_match(db, user_id=user_id, item=item)
    if book is None:
        book = create_book_from_libby_item(user_id, item)
        db.add(book)
        db.flush()
        return LibbyBookResult(book=book, created=True, updated=False)

    updated = fill_empty_book_fields(book, item)
    if updated:
        db.flush()
    return LibbyBookResult(book=book, created=False, updated=updated)


def create_libby_reading_event(
    db: Session,
    *,
    user_id: int,
    book_id: int,
    item: LibbyTimelineItem,
    event_type: str,
) -> LibbyEventResult:
    if item.timestamp is None:
        raise ValueError("Libby timeline item must include a timestamp to create a reading event.")

    source_event_id = build_libby_source_event_id(item)
    existing_event = db.scalars(
        select(ReadingEvent).where(
            ReadingEvent.user_id == user_id,
            ReadingEvent.source == "libby",
            ReadingEvent.source_event_id == source_event_id,
        )
    ).first()
    if existing_event is not None:
        return LibbyEventResult(event=existing_event, created=False)

    event = ReadingEvent(
        user_id=user_id,
        book_id=book_id,
        source="libby",
        source_event_id=source_event_id,
        event_type=event_type,
        event_date=item.timestamp,
        raw_data={"libby": item.raw_item},
    )
    db.add(event)
    db.flush()
    return LibbyEventResult(event=event, created=True)


def process_libby_timeline_items(
    db: Session,
    *,
    user_id: int,
    items: list[LibbyTimelineItem],
) -> LibbyImportSummary:
    books_created = 0
    books_updated = 0
    events_created = 0
    events_skipped = 0
    unsupported_events = 0
    book_ids: list[int] = []

    for item in items:
        book_result = upsert_libby_book(db, user_id=user_id, item=item)
        if book_result.book.id not in book_ids:
            book_ids.append(book_result.book.id)
        if book_result.created:
            books_created += 1
        elif book_result.updated:
            books_updated += 1

        event_type = libby_activity_to_event_type(item.activity)
        if event_type is None or item.timestamp is None:
            unsupported_events += 1
            continue

        event_result = create_libby_reading_event(
            db,
            user_id=user_id,
            book_id=book_result.book.id,
            item=item,
            event_type=event_type,
        )
        if event_result.created:
            events_created += 1
        else:
            events_skipped += 1

    return LibbyImportSummary(
        books_created=books_created,
        books_updated=books_updated,
        events_created=events_created,
        events_skipped=events_skipped,
        unsupported_events=unsupported_events,
        book_ids=tuple(book_ids),
    )
