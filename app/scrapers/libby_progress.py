from __future__ import annotations

from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import re


PERCENT_PATTERN = re.compile(r"(?P<percent>\d{1,3}(?:\.\d+)?)\s*%")
PAGE_PATTERN = re.compile(r"(?:page|p\.)\s*(?P<position>\d+)\s*(?:of|/)\s*(?P<total>\d+)", re.IGNORECASE)
TIME_PATTERN = re.compile(
    r"(?P<position>\d+\s*(?:h|hr|hrs|hour|hours)(?:\s+\d+\s*(?:m|min|mins|minute|minutes))?|\d+\s*(?:m|min|mins|minute|minutes))"
    r"\s*(?:of|/)\s*"
    r"(?P<total>\d+\s*(?:h|hr|hrs|hour|hours)(?:\s+\d+\s*(?:m|min|mins|minute|minutes))?|\d+\s*(?:m|min|mins|minute|minutes))",
    re.IGNORECASE,
)
HOURS_PATTERN = re.compile(r"(?P<hours>\d+)\s*(?:h|hr|hrs|hour|hours)", re.IGNORECASE)
MINUTES_PATTERN = re.compile(r"(?P<minutes>\d+)\s*(?:m|min|mins|minute|minutes)", re.IGNORECASE)
COMPLETED_PATTERN = re.compile(r"\b(completed|finished|100\s*%)\b", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class LibbyProgressParseResult:
    source: str = "scraped"
    parser_version: str = "libby-progress-v1"
    progress_percent: float | None = None
    position_pages: int | None = None
    total_pages: int | None = None
    position_seconds: int | None = None
    total_seconds: int | None = None
    status_inferred: str | None = None
    progress_text: str | None = None

    def as_book_progress_values(self) -> dict[str, object]:
        return {
            "source": self.source,
            "progress_percent": self.progress_percent,
            "position_pages": self.position_pages,
            "total_pages": self.total_pages,
            "position_seconds": self.position_seconds,
            "total_seconds": self.total_seconds,
            "status_inferred": self.status_inferred,
        }

    def as_snapshot_raw_data(self) -> dict[str, object]:
        return asdict(self)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self.parts)


def normalize_scraped_text(content: str, *, content_type: str | None = None) -> str:
    if content_type == "text/html" or "<" in content and ">" in content:
        extractor = TextExtractor()
        extractor.feed(content)
        content = extractor.text()
    return WHITESPACE_PATTERN.sub(" ", content).strip()


def clamp_percent(value: float) -> float:
    return max(0, min(100, value))


def parse_time_seconds(value: str) -> int:
    hours_match = HOURS_PATTERN.search(value)
    minutes_match = MINUTES_PATTERN.search(value)
    hours = int(hours_match.group("hours")) if hours_match else 0
    minutes = int(minutes_match.group("minutes")) if minutes_match else 0
    return hours * 3600 + minutes * 60


def infer_status(progress_percent: float | None) -> str | None:
    if progress_percent is None:
        return None
    if progress_percent >= 98:
        return "completed"
    if progress_percent > 0:
        return "started"
    return "borrowed"


def parse_libby_progress(content: str, *, content_type: str | None = None) -> LibbyProgressParseResult:
    text = normalize_scraped_text(content, content_type=content_type)
    progress_percent: float | None = None
    position_pages: int | None = None
    total_pages: int | None = None
    position_seconds: int | None = None
    total_seconds: int | None = None

    percent_match = PERCENT_PATTERN.search(text)
    if percent_match:
        progress_percent = clamp_percent(float(percent_match.group("percent")))

    page_match = PAGE_PATTERN.search(text)
    if page_match:
        position_pages = int(page_match.group("position"))
        total_pages = int(page_match.group("total"))
        if progress_percent is None and total_pages:
            progress_percent = clamp_percent(position_pages / total_pages * 100)

    time_match = TIME_PATTERN.search(text)
    if time_match:
        position_seconds = parse_time_seconds(time_match.group("position"))
        total_seconds = parse_time_seconds(time_match.group("total"))
        if progress_percent is None and total_seconds:
            progress_percent = clamp_percent(position_seconds / total_seconds * 100)

    if progress_percent is None and COMPLETED_PATTERN.search(text):
        progress_percent = 100

    return LibbyProgressParseResult(
        progress_percent=progress_percent,
        position_pages=position_pages,
        total_pages=total_pages,
        position_seconds=position_seconds,
        total_seconds=total_seconds,
        status_inferred=infer_status(progress_percent),
        progress_text=text or None,
    )
