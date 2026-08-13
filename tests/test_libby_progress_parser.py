from pathlib import Path

from app.scrapers.libby_progress import parse_libby_progress


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
