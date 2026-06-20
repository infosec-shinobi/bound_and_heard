from datetime import datetime, timezone

import pytest

from app.importers.libby_json import LibbyParseError, parse_libby_export


def sample_export() -> dict[str, object]:
    return {
        "version": 1,
        "timeline": [
            {
                "cover": {
                    "contentType": "image/jpeg",
                    "url": "https://example.test/cover.jpg",
                    "title": "Cover Title",
                    "color": "#123456",
                    "format": "audiobook",
                },
                "title": {
                    "text": "A Sample Book",
                    "url": "https://share.libbyapp.com/title/12345",
                    "titleId": "12345",
                },
                "author": "Example Author",
                "publisher": "Example Publisher",
                "isbn": "9781234567890",
                "timestamp": 1767903363000,
                "activity": "Borrowed",
                "details": " 21 days ",
                "library": {
                    "text": "Example Library",
                    "url": "https://library.example.test",
                    "key": "examplelibrary",
                },
            }
        ],
    }


def test_parse_libby_export_extracts_top_level_version_and_timeline() -> None:
    parsed = parse_libby_export(sample_export())

    assert parsed.version == 1
    assert len(parsed.timeline) == 1


def test_parse_libby_timeline_item_extracts_documented_fields() -> None:
    raw_export = sample_export()
    parsed = parse_libby_export(raw_export)
    item = parsed.timeline[0]

    assert item.cover.content_type == "image/jpeg"
    assert item.cover.url == "https://example.test/cover.jpg"
    assert item.cover.title == "Cover Title"
    assert item.cover.color == "#123456"
    assert item.cover.format == "audiobook"
    assert item.title.text == "A Sample Book"
    assert item.title.url == "https://share.libbyapp.com/title/12345"
    assert item.title.title_id == "12345"
    assert item.author == "Example Author"
    assert item.publisher == "Example Publisher"
    assert item.isbn == "9781234567890"
    assert item.timestamp_ms == 1767903363000
    assert item.timestamp == datetime(2026, 1, 8, 20, 16, 3, tzinfo=timezone.utc)
    assert item.activity == "Borrowed"
    assert item.details == " 21 days "
    assert item.library.text == "Example Library"
    assert item.library.url == "https://library.example.test"
    assert item.library.key == "examplelibrary"
    assert item.raw_item is raw_export["timeline"][0]


def test_parse_libby_export_allows_missing_optional_item_metadata() -> None:
    parsed = parse_libby_export({"version": 1, "timeline": [{}]})
    item = parsed.timeline[0]

    assert item.cover.content_type is None
    assert item.title.text is None
    assert item.author is None
    assert item.publisher is None
    assert item.isbn is None
    assert item.timestamp_ms is None
    assert item.timestamp is None
    assert item.activity is None
    assert item.details is None
    assert item.library.key is None
    assert item.raw_item == {}


def test_parse_libby_export_requires_object() -> None:
    with pytest.raises(LibbyParseError, match="Libby export must be a JSON object"):
        parse_libby_export([])


def test_parse_libby_export_requires_timeline_array() -> None:
    with pytest.raises(LibbyParseError, match="timeline array"):
        parse_libby_export({"version": 1, "timeline": {}})


def test_parse_libby_export_requires_timeline_items_to_be_objects() -> None:
    with pytest.raises(LibbyParseError, match="Timeline item 0 must be an object"):
        parse_libby_export({"version": 1, "timeline": ["bad"]})
