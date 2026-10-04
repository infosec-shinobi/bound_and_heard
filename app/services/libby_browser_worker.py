import sys
from pathlib import Path


DESKTOP_CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def main() -> int:
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--headless"):
        print("Usage: python -m app.services.libby_browser_worker <profile_dir> [--headless]", file=sys.stderr)
        return 2

    profile_dir = sys.argv[1]
    headless = len(sys.argv) == 3
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=headless,
        user_agent=DESKTOP_CHROME_USER_AGENT,
        no_viewport=True,
        locale="en-US",
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://libbyapp.com/", wait_until="domcontentloaded")

    print("Libby browser session is open. Close this window/process after logging in.")
    try:
        page.wait_for_timeout(24 * 60 * 60 * 1000)
    finally:
        context.close()
        playwright.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
