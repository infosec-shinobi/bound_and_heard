from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
from pathlib import Path
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, LibbySeriesSnapshot, Series, SeriesBook
from app.services.scrape_snapshots import snapshot_checksum


WHITESPACE_PATTERN = re.compile(r"\s+")
DATA_TITLE_PATTERN = re.compile(r"(?:^|\s)data-title_(?P<title_id>\d+)(?:\s|$)")
FORMAT_PATTERN = re.compile(r"(?:^|\s)data-title-tile-format_(?P<format>[a-z_]+)(?:\s|$)")
SERIES_KEY_PATTERN = re.compile(r"/shelf/(?P<key>series-\d+)/page-\d+")
POSITION_PATTERN = re.compile(r"#?(?P<position>-?\d+(?:\.\d+)?)\s+in\s+series", re.IGNORECASE)
POSITION_RANGE_PATTERN = re.compile(r"#?(?P<start>-?\d+(?:\.\d+)?)\s*-\s*(?P<end>-?\d+(?:\.\d+)?)\s+in\s+series", re.IGNORECASE)
PAGE_TITLE_PATTERN = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
TITLE_TILE_PATTERN = re.compile(r'<div\s+class="(?P<class>[^"]*\btitle-tile\b[^"]*)"[^>]*>', re.IGNORECASE)
ACTION_PATTERN = re.compile(
    r'<a\s+class="[^"]*\btitle-tile-action\b[^"]*"(?P<attrs>[^>]*)>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
HREF_PATTERN = re.compile(r'href="(?P<href>[^"]+)"', re.IGNORECASE)
ARIA_LABEL_PATTERN = re.compile(r'aria-label="(?P<label>[^"]+)"', re.IGNORECASE)
TITLE_TEXT_PATTERN = re.compile(r'<span\s+class="title-tile-title"[^>]*>(?P<title>.*?)</span>', re.IGNORECASE | re.DOTALL)
AUTHOR_PATTERN = re.compile(r'<div\s+class="title-tile-author"[^>]*>.*?<a[^>]*>(?P<author>.*?)</a>', re.IGNORECASE | re.DOTALL)
AUTHOR_DIV_PATTERN = re.compile(r'<div\s+class="title-tile-author"[^>]*>(?P<author>.*?)</div>', re.IGNORECASE | re.DOTALL)
SERIES_NUMBER_PATTERN = re.compile(r'<button\s+class="[^"]*\bseries-number\b[^"]*"[^>]*>(?P<body>.*?)</button>', re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class LibbySeriesPageEntry:
    title: str
    author: str | None
    format: str
    available_formats: tuple[str, ...]
    position: float | None
    position_end: float | None
    raw_position_label: str | None
    libby_title_id: str | None
    libby_title_url: str | None

    @property
    def display_format(self) -> str:
        return ", ".join(format_name.replace("_", " ").title() for format_name in self.available_formats) or "Unknown"


@dataclass(frozen=True)
class LibbySeriesPage:
    series_name: str | None
    libby_series_key: str | None
    entries: tuple[LibbySeriesPageEntry, ...]


@dataclass(frozen=True)
class LibbySeriesPopulationPreviewItem:
    entry: LibbySeriesPageEntry
    action: str
    reason: str
    matched_book: Book | None = None


@dataclass(frozen=True)
class LibbySeriesPopulationPreview:
    page: LibbySeriesPage
    items: tuple[LibbySeriesPopulationPreviewItem, ...]

    @property
    def add_book_count(self) -> int:
        return sum(1 for item in self.items if item.action == "add_book")

    @property
    def planned_count(self) -> int:
        return sum(1 for item in self.items if item.action == "add_planned")

    @property
    def skip_count(self) -> int:
        return sum(1 for item in self.items if item.action == "skip")


@dataclass(frozen=True)
class LibbySeriesPopulationResult:
    preview: LibbySeriesPopulationPreview
    added_books: int
    added_planned: int
    skipped: int


@dataclass(frozen=True)
class PreservedLibbySeriesSnapshot:
    snapshot: LibbySeriesSnapshot
    content: bytes


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = WHITESPACE_PATTERN.sub(" ", str(value).replace("\xa0", " ")).strip()
    return cleaned or None


def normalize_text(value: str | None) -> str | None:
    value = clean_text(value)
    if value is None:
        return None
    return value.casefold()


def normalize_libby_format(value: str | None) -> str:
    if value == "audiobook":
        return "audiobook"
    if value == "book":
        return "ebook"
    return "unknown"


def parse_position(value: str | None) -> float | None:
    if value is None:
        return None
    range_match = POSITION_RANGE_PATTERN.search(value)
    if range_match:
        return float(range_match.group("start"))
    match = POSITION_PATTERN.search(value)
    return float(match.group("position")) if match else None


def parse_position_end(value: str | None) -> float | None:
    if value is None:
        return None
    range_match = POSITION_RANGE_PATTERN.search(value)
    return float(range_match.group("end")) if range_match else None


def parse_series_name_from_title(value: str | None) -> str | None:
    if value and value.startswith("Libby - "):
        return value.removeprefix("Libby - ").strip() or None
    return value


def parse_libby_series_page(content: str) -> LibbySeriesPage:
    page_title_match = PAGE_TITLE_PATTERN.search(content)
    entries: list[LibbySeriesPageEntry] = []
    matches = [match for match in TITLE_TILE_PATTERN.finditer(content) if "title-tile" in match.group("class").split()]
    libby_series_key: str | None = None

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        chunk = content[start:end]
        class_name = match.group("class")
        data_title_match = DATA_TITLE_PATTERN.search(class_name)
        format_match = FORMAT_PATTERN.search(class_name)
        action_match = ACTION_PATTERN.search(chunk)
        if not action_match:
            continue

        href = regex_group(HREF_PATTERN, action_match.group("attrs"), "href")
        if href:
            key_match = SERIES_KEY_PATTERN.search(href)
            if key_match:
                libby_series_key = key_match.group("key")
        raw_title = regex_group(TITLE_TEXT_PATTERN, action_match.group("body"), "title")
        aria_label = regex_group(ARIA_LABEL_PATTERN, action_match.group("attrs"), "label")
        title = strip_html(raw_title)
        author = strip_html(regex_group(AUTHOR_PATTERN, chunk, "author") or regex_group(AUTHOR_DIV_PATTERN, chunk, "author"))
        if aria_label and (not title or not author):
            aria_match = re.match(r"(?:Book|Audiobook):\s*(?P<title>.+?),\s+by\s+(?P<author>.+)$", html.unescape(aria_label))
            if aria_match:
                title = title or clean_text(aria_match.group("title"))
                author = author or clean_text(aria_match.group("author"))
        if not title:
            continue

        raw_position_label = strip_html(regex_group(SERIES_NUMBER_PATTERN, chunk, "body"))
        entries.append(
            LibbySeriesPageEntry(
                title=title,
                author=author,
                format=normalize_libby_format(format_match.group("format") if format_match else None),
                available_formats=(normalize_libby_format(format_match.group("format") if format_match else None),),
                position=parse_position(raw_position_label),
                position_end=parse_position_end(raw_position_label),
                raw_position_label=raw_position_label,
                libby_title_id=data_title_match.group("title_id") if data_title_match else None,
                libby_title_url=href,
            )
        )

    return LibbySeriesPage(
        series_name=parse_series_name_from_title(strip_html(page_title_match.group("title")) if page_title_match else None),
        libby_series_key=libby_series_key,
        entries=tuple(entries),
    )


def regex_group(pattern: re.Pattern[str], value: str, name: str) -> str | None:
    match = pattern.search(value)
    return match.group(name) if match else None


def strip_html(value: str | None) -> str | None:
    if value is None:
        return None
    return clean_text(html.unescape(TAG_PATTERN.sub(" ", value)))


def build_libby_series_population_preview(
    db: Session,
    *,
    user_id: int,
    series_id: int,
    content: str,
    include_unmatched: bool,
) -> LibbySeriesPopulationPreview:
    page = parse_libby_series_page(content)
    books = db.scalars(select(Book).where(Book.user_id == user_id)).all()
    existing_entries = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series_id)).all()
    existing_book_ids = {entry.book_id for entry in existing_entries if entry.book_id is not None}
    existing_planned_keys = {planned_key(entry.planned_title, entry.planned_author_name, entry.planned_format, entry.position) for entry in existing_entries if entry.book_id is None}
    existing_planned_loose_keys = {planned_loose_key(entry.planned_title, entry.planned_author_name, entry.planned_format) for entry in existing_entries if entry.book_id is None}
    existing_planned_title_keys = {planned_title_key(entry.planned_title, entry.position) for entry in existing_entries if entry.book_id is None}
    entries = unique_work_entries(page.entries)
    items: list[LibbySeriesPopulationPreviewItem] = []
    planned_keys_seen: set[tuple[str | None, str | None, str | None, float | None]] = set()

    for entry in entries:
        matched_book = match_book_for_libby_entry(books, entry)
        if matched_book is not None:
            if matched_book.id in existing_book_ids:
                items.append(LibbySeriesPopulationPreviewItem(entry=entry, action="skip", reason="Already assigned to this series", matched_book=matched_book))
            else:
                items.append(LibbySeriesPopulationPreviewItem(entry=entry, action="add_book", reason="Matched local book", matched_book=matched_book))
            continue

        key = planned_key(entry.title, entry.author, entry.format, entry.position)
        loose_key = planned_loose_key(entry.title, entry.author, entry.format)
        title_key = planned_title_key(entry.title, entry.position)
        if key in existing_planned_keys or loose_key in existing_planned_loose_keys or title_key in existing_planned_title_keys or key in planned_keys_seen:
            items.append(LibbySeriesPopulationPreviewItem(entry=entry, action="skip", reason="Planned entry already exists"))
        elif include_unmatched:
            items.append(LibbySeriesPopulationPreviewItem(entry=entry, action="add_planned", reason="No local book matched"))
            planned_keys_seen.add(key)
        else:
            items.append(LibbySeriesPopulationPreviewItem(entry=entry, action="skip", reason="No local book matched"))

    return LibbySeriesPopulationPreview(
        page=LibbySeriesPage(series_name=page.series_name, libby_series_key=page.libby_series_key, entries=tuple(entries)),
        items=tuple(items),
    )


def apply_libby_series_population(
    db: Session,
    *,
    user_id: int,
    series_id: int,
    content: str,
    include_unmatched: bool,
) -> LibbySeriesPopulationResult:
    preview = build_libby_series_population_preview(db, user_id=user_id, series_id=series_id, content=content, include_unmatched=include_unmatched)
    added_books = 0
    added_planned = 0
    skipped = 0
    for item in preview.items:
        if item.action == "add_book" and item.matched_book is not None:
            db.add(
                SeriesBook(
                    series_id=series_id,
                    book_id=item.matched_book.id,
                    position=item.entry.position,
                    position_end=item.entry.position_end,
                )
            )
            added_books += 1
        elif item.action == "add_planned":
            db.add(
                SeriesBook(
                    series_id=series_id,
                    position=item.entry.position,
                    position_end=item.entry.position_end,
                    planned_title=item.entry.title,
                    planned_author_name=item.entry.author,
                    planned_format=item.entry.format,
                    notes=f"Imported from Libby series page{f' ({item.entry.libby_title_id})' if item.entry.libby_title_id else ''}.",
                )
            )
            added_planned += 1
        else:
            skipped += 1
    return LibbySeriesPopulationResult(preview=preview, added_books=added_books, added_planned=added_planned, skipped=skipped)


def latest_libby_series_snapshot(db: Session, *, series_id: int, user_id: int) -> LibbySeriesSnapshot | None:
    return db.scalars(
        select(LibbySeriesSnapshot)
        .where(LibbySeriesSnapshot.series_id == series_id, LibbySeriesSnapshot.user_id == user_id)
        .order_by(LibbySeriesSnapshot.created_at.desc(), LibbySeriesSnapshot.id.desc())
    ).first()


def suggested_libby_series_url(db: Session, *, series: Series) -> str | None:
    snapshot = latest_libby_series_snapshot(db, series_id=series.id, user_id=series.user_id)
    if snapshot is not None:
        return snapshot.libby_series_url
    for entry in series.books:
        if entry.book is None:
            continue
        for hint in entry.book.libby_series_hints:
            if hint.libby_series_url:
                return absolute_libby_url(hint.libby_series_url)
    return None


def absolute_libby_url(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"https://libbyapp.com{value}"
    return f"https://libbyapp.com/{value}"


def read_libby_series_snapshot_content(snapshot: LibbySeriesSnapshot) -> str:
    return Path(snapshot.file_path).read_text(encoding="utf-8")


def preserve_libby_series_snapshot(
    db: Session,
    *,
    series: Series,
    base_dir: str,
    libby_series_url: str,
    content: str | bytes,
    content_type: str | None = "text/html",
    raw_data: dict | None = None,
) -> PreservedLibbySeriesSnapshot:
    content_bytes = content.encode("utf-8") if isinstance(content, str) else content
    checksum = snapshot_checksum(content_bytes)
    parsed = parse_libby_series_page(content_bytes.decode("utf-8", errors="replace"))
    unique_entries = unique_work_entries(parsed.entries)
    captured_at = datetime.now(timezone.utc)
    target_dir = Path(base_dir) / "libby" / "series" / f"series-{series.id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{captured_at.strftime('%Y%m%d%H%M%S')}-series-{checksum[:12]}.html"
    target_path.write_bytes(content_bytes)
    snapshot = LibbySeriesSnapshot(
        user_id=series.user_id,
        series_id=series.id,
        libby_series_key=parsed.libby_series_key,
        libby_series_url=libby_series_url,
        file_path=target_path.as_posix(),
        checksum=checksum,
        content_type=content_type,
        parsed_entry_count=len(unique_entries),
        raw_data={
            **(raw_data or {}),
            "parser": "libby-series-page-v1",
            "series_name": parsed.series_name,
            "entry_count": len(unique_entries),
            "raw_tile_count": len(parsed.entries),
        },
    )
    db.add(snapshot)
    return PreservedLibbySeriesSnapshot(snapshot=snapshot, content=content_bytes)


def match_book_for_libby_entry(books: list[Book], entry: LibbySeriesPageEntry) -> Book | None:
    if entry.libby_title_id:
        matches = [book for book in books if book.libby_title_id == entry.libby_title_id]
        if len(matches) == 1:
            return matches[0]

    title = normalize_text(entry.title)
    author = normalize_text(entry.author)
    if title is None:
        return None
    if author is None:
        matches = [book for book in books if normalize_text(book.title) == title]
        return matches[0] if len(matches) == 1 else None

    matches = [book for book in books if normalize_text(book.title) == title and normalize_text(book.primary_author_name) == author]
    if len(matches) == 1:
        return matches[0]
    title_matches = [book for book in books if normalize_text(book.title) == title]
    return title_matches[0] if len(title_matches) == 1 else None


def unique_work_entries(entries: tuple[LibbySeriesPageEntry, ...]) -> tuple[LibbySeriesPageEntry, ...]:
    by_key: dict[tuple[str | None, str | None, float | None], LibbySeriesPageEntry] = {}
    formats_by_key: dict[tuple[str | None, str | None, float | None], set[str]] = {}
    for entry in entries:
        key = work_key(entry)
        formats_by_key.setdefault(key, set()).add(entry.format)
        existing = by_key.get(key)
        if existing is None or (existing.libby_title_id is None and entry.libby_title_id is not None):
            by_key[key] = entry

    unique_entries: list[LibbySeriesPageEntry] = []
    for key, entry in by_key.items():
        formats = formats_by_key[key]
        if len(formats) > 1:
            entry = LibbySeriesPageEntry(
                title=entry.title,
                author=entry.author,
                format="unknown",
                available_formats=tuple(sorted(formats)),
                position=entry.position,
                position_end=entry.position_end,
                raw_position_label=entry.raw_position_label,
                libby_title_id=entry.libby_title_id,
                libby_title_url=entry.libby_title_url,
            )
        elif entry.available_formats != tuple(sorted(formats)):
            entry = LibbySeriesPageEntry(
                title=entry.title,
                author=entry.author,
                format=entry.format,
                available_formats=tuple(sorted(formats)),
                position=entry.position,
                position_end=entry.position_end,
                raw_position_label=entry.raw_position_label,
                libby_title_id=entry.libby_title_id,
                libby_title_url=entry.libby_title_url,
            )
        unique_entries.append(entry)
    return tuple(unique_entries)


def work_key(entry: LibbySeriesPageEntry) -> tuple[str | None, str | None, float | None, float | None]:
    return (normalize_text(entry.title), normalize_text(entry.author), entry.position, entry.position_end)


def planned_key(title: str | None, author: str | None, book_format: str | None, position: float | None) -> tuple[str | None, str | None, str | None, float | None]:
    return (normalize_text(title), normalize_text(author), book_format, position)


def planned_loose_key(title: str | None, author: str | None, book_format: str | None) -> tuple[str | None, str | None, str | None]:
    return (normalize_text(title), normalize_text(author), book_format)


def planned_title_key(title: str | None, position: float | None) -> tuple[str | None, float | None]:
    return (normalize_text(title), position)
