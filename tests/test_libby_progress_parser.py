from pathlib import Path

from app.scrapers.libby_progress import parse_libby_progress, parse_libby_series_hint


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "libby_progress"


def read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_parse_ebook_partial_progress_from_html_fixture() -> None:
    result = parse_libby_progress(read_fixture("ebook_partial.html"), content_type="text/html")

    assert result.source == "scraped"
    assert result.parser_version == "libby-progress-v1"
    assert result.progress_percent == 42
    assert result.position_pages == 126
    assert result.total_pages == 300
    assert result.status_inferred == "started"
    assert result.as_book_progress_values() == {
        "source": "scraped",
        "progress_percent": 42,
        "position_pages": 126,
        "total_pages": 300,
        "position_seconds": None,
        "total_seconds": None,
        "enjoyed_seconds": None,
        "read_count": None,
        "status_inferred": "started",
    }


def test_parse_audiobook_partial_progress_from_text_fixture() -> None:
    result = parse_libby_progress(read_fixture("audiobook_partial.txt"), content_type="text/plain")

    assert result.progress_percent == 25
    assert result.position_seconds == 9000
    assert result.total_seconds == 36000
    assert result.status_inferred == "started"


def test_parse_completed_progress_from_text_fixture() -> None:
    result = parse_libby_progress(read_fixture("completed.txt"), content_type="text/plain")

    assert result.progress_percent == 100
    assert result.status_inferred == "completed"


def test_parse_page_progress_derives_percent_when_no_percent_exists() -> None:
    result = parse_libby_progress("Page 50 of 200", content_type="text/plain")

    assert result.progress_percent == 25
    assert result.position_pages == 50
    assert result.total_pages == 200


def test_parse_duration_progress_derives_percent_when_no_percent_exists() -> None:
    result = parse_libby_progress("1 hr of 4 hr", content_type="text/plain")

    assert result.progress_percent == 25
    assert result.position_seconds == 3600
    assert result.total_seconds == 14400


def test_parse_no_progress_yet_from_journey_text() -> None:
    result = parse_libby_progress("Reading journey No progress yet", content_type="text/plain")

    assert result.progress_percent == 0
    assert result.status_inferred == "borrowed"


def test_parse_title_timeline_direct_borrowed_date_as_start_date() -> None:
    result = parse_libby_progress(
        "Reading Journey No progress yet. Title Timeline Borrowed. 7 MAY 2018 7 MAY '18 At Your Libraries",
        content_type="text/plain",
    )

    assert result.started_on is not None
    assert result.started_on.isoformat() == "2018-05-07"
    assert result.latest_borrowed_on is not None
    assert result.latest_borrowed_on.isoformat() == "2018-05-07"


def test_parse_title_timeline_uses_tagged_date_before_dateless_borrowed_event() -> None:
    result = parse_libby_progress(
        "Reading Journey Starting on 14 Nov 2021, you picked up this audiobook 23 times, reading for 12 hours, 5 minutes. "
        "Title Timeline Tagged with Tag: receipt 14 NOV 2021 14 NOV '21 Borrowed. At Your Libraries",
        content_type="text/plain",
    )

    assert result.started_on is not None
    assert result.started_on.isoformat() == "2021-11-14"
    assert result.latest_borrowed_on is not None
    assert result.latest_borrowed_on.isoformat() == "2021-11-14"


def test_parse_title_timeline_tracks_earliest_and_latest_borrowed_dates() -> None:
    result = parse_libby_progress(
        "Completed. Title Timeline Borrowed. 3 AUG 2022 3 AUG '22 Borrowed. 16 MAY 2025 16 MAY '25 At Your Libraries",
        content_type="text/plain",
    )

    assert result.started_on is not None
    assert result.started_on.isoformat() == "2022-08-03"
    assert result.latest_borrowed_on is not None
    assert result.latest_borrowed_on.isoformat() == "2025-05-16"


def test_infer_completed_status_starts_at_98_percent() -> None:
    result = parse_libby_progress("98%", content_type="text/plain")

    assert result.status_inferred == "completed"


def test_parse_journey_listened_and_time_left_text() -> None:
    result = parse_libby_progress("Reading journey You have listened 2 hr 30 min 7 hr 30 min left", content_type="text/plain")

    assert result.progress_percent == 25
    assert result.position_seconds == 9000
    assert result.enjoyed_seconds == 9000
    assert result.remaining_seconds == 27000
    assert result.total_seconds == 36000


def test_parse_libby_journey_reading_for_duration_without_time_left() -> None:
    result = parse_libby_progress(
        "Starting on 28 Mar, you picked up this audiobook 12 times, reading for 5 hours, 42 minutes.",
        content_type="text/plain",
    )

    assert result.position_seconds == 20520
    assert result.enjoyed_seconds == 20520
    assert result.read_count is None
    assert result.total_seconds is None
    assert result.progress_percent is None


def test_parse_libby_journey_reading_for_duration_and_finish_in_duration() -> None:
    result = parse_libby_progress(
        "Since 3 Aug, you have picked up this audiobook 12 times, reading for 5 hours, 38 minutes. You're on track to finish in 4 hours, 51 minutes.",
        content_type="text/plain",
    )

    assert result.position_seconds == 20280
    assert result.enjoyed_seconds == 20280
    assert result.remaining_seconds == 17460
    assert result.total_seconds == 37740
    assert round(result.progress_percent or 0) == 54
    assert result.status_inferred == "started"


def test_parse_libby_journey_duration_with_space_before_comma() -> None:
    result = parse_libby_progress(
        "Since 3 Aug, reading for 5 hours , 38 minutes. You're on track to finish in 4 hours , 51 minutes.",
        content_type="text/plain",
    )

    assert result.position_seconds == 20280
    assert result.remaining_seconds == 17460


def test_parse_libby_progress_needle_width_from_html() -> None:
    result = parse_libby_progress(
        '<div class="screen-shelf-journey-progress-needle" style="width: 53.7587%;"></div>',
        content_type="text/html",
    )

    assert result.progress_percent == 53.7587
    assert result.status_inferred == "started"


def test_parse_libby_progress_needle_does_not_use_unrelated_css_width() -> None:
    result = parse_libby_progress('<style>.x { width: 100%; }</style>', content_type="text/html")

    assert result.progress_percent is None


def test_parse_libby_series_hint_from_journey_html() -> None:
    html = '<a class="halo" href="/shelf/series-503231/page-1"><strong><span role="text">Series</span></strong><cite><span role="text">#26 in Jack Reacher</span></cite></a>'

    hint = parse_libby_series_hint(html, content_type="text/html")

    assert hint is not None
    assert hint.libby_series_key == "series-503231"
    assert hint.libby_series_url == "/shelf/series-503231/page-1"
    assert hint.raw_label == "#26 in Jack Reacher"
    assert hint.series_name == "Jack Reacher"
    assert hint.position == 26


def test_parse_libby_progress_includes_series_hint_from_html() -> None:
    result = parse_libby_progress(
        '<div class="screen-shelf-journey-progress-needle" style="width: 53%;"></div><a class="halo" href="/shelf/series-503231/page-1"><strong><span role="text">Series</span></strong><cite><span role="text">#26 in Jack Reacher</span></cite></a>',
        content_type="text/html",
    )

    assert result.series_hint is not None
    assert result.series_hint.series_name == "Jack Reacher"
