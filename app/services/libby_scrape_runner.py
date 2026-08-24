from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import ScrapeJob, ScrapeJobItem, Series
from app.scrapers.libby_progress import parse_libby_progress
from app.services.libby_series import absolute_libby_url, preserve_libby_series_snapshot
from app.services.scrape_progress import apply_scraped_progress
from app.services.scrape_safety import wait_polite_delay
from app.services.scrape_snapshots import preserve_scrape_snapshot


class LibbyScrapeRunnerError(RuntimeError):
    pass


JOURNEY_READY_SCRIPT = r"""
() => {
  const text = document.body?.innerText || '';
  const stillLoading = /Updating|LOADING|Loading/.test(text);
  const hasJourneySignal = /No progress yet|\d+(?:\.\d+)?\s*%|\b(?:left|remaining|listened|read|completed|finished)\b/i.test(text);
  return !stillLoading && hasJourneySignal;
}
"""

SERIES_READY_SCRIPT = r"""
() => {
  const text = document.body?.innerText || '';
  const stillLoading = /Updating|LOADING|Loading/.test(text);
  const hasSeriesSignal = /Page\s+\d+\s+of\s+\d+|\btitle-tile\b|\bin series\b/i.test(document.body?.innerHTML || text);
  return !stillLoading && hasSeriesSignal;
}
"""

SERIES_SCROLL_SCRIPT = r"""
async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const scrollers = Array.from(document.querySelectorAll('.native-scrollable-y, .scroller'));
  const targets = [document.scrollingElement || document.documentElement, ...scrollers].filter(Boolean);
  for (let pass = 0; pass < 8; pass += 1) {
    for (const target of targets) {
      target.scrollTop = target.scrollHeight;
    }
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(350);
  }
  for (const target of targets) {
    target.scrollTop = 0;
  }
  window.scrollTo(0, 0);
  await sleep(250);
}
"""


def scrape_url_for_item(item: ScrapeJobItem) -> str:
    book = item.book
    if not book.libby_title_id:
        raise LibbyScrapeRunnerError("Book is missing Libby title ID.")
    return f"https://libbyapp.com/shelf/journey/{book.libby_title_id}"


def has_parseable_progress(parsed: object) -> bool:
    return any(
        getattr(parsed, field_name, None) is not None
        for field_name in ("progress_percent", "position_pages", "position_seconds")
    )


def prepare_libby_series_page(page: object) -> None:
    from playwright.sync_api import Error as PlaywrightError

    try:
        page.wait_for_function(SERIES_READY_SCRIPT, timeout=30_000)
    except PlaywrightError:
        pass
    try:
        page.evaluate(SERIES_SCROLL_SCRIPT)
        page.wait_for_function(SERIES_READY_SCRIPT, timeout=10_000)
    except PlaywrightError:
        pass


def collect_libby_series_html(page: object, *, url: str) -> tuple[str, list[str]]:
    captured: list[tuple[str, str]] = []
    page.goto(url, wait_until="domcontentloaded")
    prepare_libby_series_page(page)
    captured.append(("initial", page.content()))

    for label in ("books", "audiobooks"):
        page.goto(url, wait_until="domcontentloaded")
        prepare_libby_series_page(page)
        try:
            button = page.locator("button.filter-button.data-category_format").filter(has_text=label).first
            if button.count() == 0:
                continue
            button.click()
            prepare_libby_series_page(page)
            captured.append((label, page.content()))
        except Exception:
            continue

    combined = "\n".join(f"<!-- libby-series-filter: {label} -->\n{content}" for label, content in captured)
    return combined, [label for label, _ in captured]


def scrape_libby_series_page(
    db: Session,
    *,
    series: Series,
    libby_series_url: str,
    profile_dir: str,
    scraped_dir: str,
) -> dict[str, object]:
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(user_data_dir=profile_dir, headless=False, locale="en-US")
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(10_000)
        page.set_default_navigation_timeout(30_000)
        target_url = absolute_libby_url(libby_series_url)
        html, captured_filters = collect_libby_series_html(page, url=target_url)
        preserved = preserve_libby_series_snapshot(
            db,
            series=series,
            base_dir=scraped_dir,
            libby_series_url=page.url,
            content=html,
            content_type="text/html",
            raw_data={"url": page.url, "captured_filters": captured_filters},
        )
        db.flush()
        return {
            "snapshot_id": preserved.snapshot.id,
            "url": page.url,
            "entry_count": preserved.snapshot.parsed_entry_count or 0,
        }
    finally:
        if context is not None:
            context.close()
        playwright.stop()


def run_libby_scrape_job(
    db: Session,
    *,
    job: ScrapeJob,
    profile_dir: str,
    scraped_dir: str,
) -> dict[str, int]:
    queued_items = [item for item in sorted(job.items, key=lambda value: (value.queued_at, value.id)) if item.status == "queued"]
    summary = {"succeeded": 0, "failed": 0, "skipped": 0}
    if not queued_items:
        return summary

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(user_data_dir=profile_dir, headless=False, locale="en-US")
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(10_000)
        page.set_default_navigation_timeout(30_000)

        for index, item in enumerate(queued_items):
            item.status = "running"
            item.started_at = datetime.now(timezone.utc)
            item.last_attempted_at = item.started_at
            item.attempts += 1
            db.flush()

            try:
                page.goto(scrape_url_for_item(item), wait_until="domcontentloaded")
                try:
                    page.wait_for_function(JOURNEY_READY_SCRIPT, timeout=30_000)
                except PlaywrightError:
                    pass
                html = page.content()
                text = page.locator("body").inner_text(timeout=10_000)
                parsed = parse_libby_progress(html, content_type="text/html")
                if parsed.progress_text is None:
                    parsed = parse_libby_progress(text, content_type="text/plain")
                preserve_scrape_snapshot(
                    db,
                    item=item,
                    base_dir=scraped_dir,
                    snapshot_type="html",
                    content=html,
                    content_type="text/html",
                    parsed_progress=parsed,
                    raw_data={"url": page.url},
                )
                preserve_scrape_snapshot(
                    db,
                    item=item,
                    base_dir=scraped_dir,
                    snapshot_type="text",
                    content=text,
                    content_type="text/plain",
                    parsed_progress=parsed,
                    raw_data={"url": page.url},
                )
                if not has_parseable_progress(parsed):
                    raise ValueError("No parseable Libby progress was found in the journey page snapshot.")
                apply_scraped_progress(db, item=item, parsed=parsed)
                item.status = "succeeded"
                item.error_code = None
                item.error_message = None
                summary["succeeded"] += 1
            except (PlaywrightError, LibbyScrapeRunnerError, ValueError) as exc:
                item.status = "failed"
                item.error_code = exc.__class__.__name__
                item.error_message = str(exc)
                summary["failed"] += 1
            finally:
                item.finished_at = datetime.now(timezone.utc)
                db.commit()

            if index < len(queued_items) - 1 and job.status != "cancelled":
                wait_polite_delay()
            if job.status == "cancelled":
                summary["skipped"] += len([remaining for remaining in queued_items[index + 1 :] if remaining.status == "queued"])
                break
    finally:
        if context is not None:
            context.close()
        playwright.stop()

    return summary
