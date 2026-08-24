from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, ScrapeJob, ScrapeJobItem, User
from app.scrapers.libby_progress import parse_libby_progress
from app.services.libby_scrape_runner import (
    JOURNEY_READY_SCRIPT,
    SERIES_SCROLL_SCRIPT,
    collect_libby_series_html,
    has_parseable_progress,
    scrape_url_for_item,
)


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_scrape_url_for_item_uses_authenticated_journey_url_not_public_share_url() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Book",
            format="ebook",
            status="borrowed",
            metadata_source="libby",
            libby_title_id="12345",
            libby_share_url="https://share.libbyapp.com/title/12345",
        )
        db.add(book)
        db.flush()
        job = ScrapeJob(user_id=DEFAULT_LOCAL_USER_ID, source="libby", status="running")
        db.add(job)
        db.flush()
        item = ScrapeJobItem(job_id=job.id, book_id=book.id, status="queued")
        db.add(item)
        db.commit()
        db.refresh(item)

        assert scrape_url_for_item(item) == "https://libbyapp.com/shelf/journey/12345"


def test_journey_ready_script_waits_for_progress_signals_not_loading_shell() -> None:
    assert "No progress yet" in JOURNEY_READY_SCRIPT
    assert "Updating" in JOURNEY_READY_SCRIPT
    assert "listened" in JOURNEY_READY_SCRIPT
    assert "\\b(?:left|remaining|listened|read|completed|finished)\\b" in JOURNEY_READY_SCRIPT


def test_series_scroll_script_targets_libby_scroll_containers() -> None:
    assert "native-scrollable-y" in SERIES_SCROLL_SCRIPT
    assert "scrollHeight" in SERIES_SCROLL_SCRIPT
    assert "window.scrollTo" in SERIES_SCROLL_SCRIPT


class FakeFilterButton:
    def __init__(self, page: "FakeSeriesPage", label: str) -> None:
        self.page = page
        self.label = label

    def count(self) -> int:
        return 1

    def click(self) -> None:
        self.page.current_filter = self.label


class FakeFilterLocator:
    def __init__(self, page: "FakeSeriesPage") -> None:
        self.page = page
        self.label = "initial"

    def filter(self, *, has_text: str) -> "FakeFilterLocator":
        self.label = has_text
        return self

    @property
    def first(self) -> FakeFilterButton:
        return FakeFilterButton(self.page, self.label)


class FakeSeriesPage:
    def __init__(self) -> None:
        self.current_filter = "initial"
        self.visited_urls: list[str] = []

    def goto(self, url: str, wait_until: str) -> None:
        self.visited_urls.append(url)
        self.current_filter = "initial"

    def wait_for_function(self, script: str, timeout: int) -> None:
        return None

    def evaluate(self, script: str) -> None:
        return None

    def locator(self, selector: str) -> FakeFilterLocator:
        assert selector == "button.filter-button.data-category_format"
        return FakeFilterLocator(self)

    def content(self) -> str:
        return f'<div class="title-tile data-title-tile-format_{self.current_filter} data-title_1"></div>'


def test_collect_libby_series_html_captures_initial_books_and_audiobooks() -> None:
    page = FakeSeriesPage()

    html, captured_filters = collect_libby_series_html(page, url="https://libbyapp.com/shelf/series-1/page-1")

    assert captured_filters == ["initial", "books", "audiobooks"]
    assert "libby-series-filter: initial" in html
    assert "libby-series-filter: books" in html
    assert "libby-series-filter: audiobooks" in html
    assert page.visited_urls == ["https://libbyapp.com/shelf/series-1/page-1"] * 3


def test_has_parseable_progress_rejects_loading_shell_text() -> None:
    parsed = parse_libby_progress("Updating LOADING Shelf Reading Journey", content_type="text/plain")

    assert has_parseable_progress(parsed) is False
