from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class LibbyParseError(ValueError):
    pass


@dataclass(frozen=True)
class LibbyCover:
    content_type: str | None
    url: str | None
    title: str | None
    color: str | None
    format: str | None


@dataclass(frozen=True)
class LibbyTitle:
    text: str | None
    url: str | None
    title_id: str | None


@dataclass(frozen=True)
class LibbyLibrary:
    text: str | None
    url: str | None
    key: str | None


@dataclass(frozen=True)
class LibbyTimelineItem:
    cover: LibbyCover
    title: LibbyTitle
    author: str | None
    publisher: str | None
    isbn: str | None
    timestamp_ms: int | None
    timestamp: datetime | None
    activity: str | None
    details: str | None
    library: LibbyLibrary
    raw_item: dict[str, Any]


@dataclass(frozen=True)
class LibbyExport:
    version: int | None
    timeline: list[LibbyTimelineItem]


def optional_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def optional_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def timestamp_from_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def parse_cover(value: object) -> LibbyCover:
    cover = optional_dict(value)
    return LibbyCover(
        content_type=optional_str(cover.get("contentType")),
        url=optional_str(cover.get("url")),
        title=optional_str(cover.get("title")),
        color=optional_str(cover.get("color")),
        format=optional_str(cover.get("format")),
    )


def parse_title(value: object) -> LibbyTitle:
    title = optional_dict(value)
    return LibbyTitle(
        text=optional_str(title.get("text")),
        url=optional_str(title.get("url")),
        title_id=optional_str(title.get("titleId")),
    )


def parse_library(value: object) -> LibbyLibrary:
    library = optional_dict(value)
    return LibbyLibrary(
        text=optional_str(library.get("text")),
        url=optional_str(library.get("url")),
        key=optional_str(library.get("key")),
    )


def parse_timeline_item(value: object, index: int) -> LibbyTimelineItem:
    if not isinstance(value, dict):
        raise LibbyParseError(f"Timeline item {index} must be an object.")

    timestamp_ms = optional_int(value.get("timestamp"))
    return LibbyTimelineItem(
        cover=parse_cover(value.get("cover")),
        title=parse_title(value.get("title")),
        author=optional_str(value.get("author")),
        publisher=optional_str(value.get("publisher")),
        isbn=optional_str(value.get("isbn")),
        timestamp_ms=timestamp_ms,
        timestamp=timestamp_from_ms(timestamp_ms),
        activity=optional_str(value.get("activity")),
        details=optional_str(value.get("details")),
        library=parse_library(value.get("library")),
        raw_item=value,
    )


def parse_libby_export(value: object) -> LibbyExport:
    if not isinstance(value, dict):
        raise LibbyParseError("Libby export must be a JSON object.")

    timeline = value.get("timeline")
    if not isinstance(timeline, list):
        raise LibbyParseError("Libby export must include a timeline array.")

    return LibbyExport(
        version=optional_int(value.get("version")),
        timeline=[parse_timeline_item(item, index) for index, item in enumerate(timeline)],
    )


def build_libby_source_event_id(item: LibbyTimelineItem) -> str:
    parts = {
        "title_id": item.title.title_id or "",
        "timestamp": str(item.timestamp_ms) if item.timestamp_ms is not None else "",
        "activity": item.activity or "",
        "library": item.library.key or "",
        "format": item.cover.format or "",
    }
    return "libby:" + "|".join(f"{key}={value}" for key, value in parts.items())
