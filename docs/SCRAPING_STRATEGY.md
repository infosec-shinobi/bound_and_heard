# Bound & Heard Scraping Strategy

## Purpose

Libby Timeline JSON provides borrowing history, but it does not provide reliable per-title completion data.

Bound & Heard will use Playwright to retrieve progress information from Libby or Libby share/reading journey pages where available.

This is a high-value feature because historical Libby libraries may contain hundreds of books that would be painful to manually classify.

## Guiding Principles

- Prefer official exports where possible.
- Scrape only when needed.
- Reuse authenticated browser state.
- Use slow, human-like pacing.
- Preserve raw snapshots.
- Make scraping resumable.
- Do not build the rest of the app around scraping success.
- Preserve partial progress when available.
- Respect manual corrections unless the user explicitly requests overwrite behavior.

## Authentication Strategy

Use Playwright persistent browser context.

The user logs into Libby manually once.

Example future implementation:

```python
browser = await chromium.launch_persistent_context(
    user_data_dir="./data/browser/libby-profile",
    headless=False,
)
```

The app should not require the user to manually copy cookies.

## Scrape Inputs

Potential scrape candidates come from imported books.

Required fields:

- libby_title_id
- libby_share_url
- latest_borrowed_at
- format
- library key, if needed

## Scrape Queue Logic

Queue a book when:

```text
book has libby_title_id
AND (
  book has never been scraped
  OR latest_borrowed_at > last_scraped_borrowed_at
)
```

Skip a book when:

```text
latest_borrowed_at <= last_scraped_borrowed_at
```

## Throttling

Use randomized delay between page fetches.

Recommended initial behavior:

```text
minimum delay: 5 seconds
maximum delay: 15 seconds
```

Use jitter so behavior is not perfectly periodic.

Example:

```python
delay = random.uniform(5, 15)
await asyncio.sleep(delay)
```

## Job Behavior

A scrape job should:

1. Identify scrape candidates.
2. Create job record.
3. Create per-book job items.
4. Process one book at a time.
5. Save raw snapshot.
6. Parse progress.
7. Update progress table.
8. Create progress/completion reading events where appropriate.
9. Mark item complete, failed, or skipped.
10. Sleep between items.
11. Continue until complete or cancelled.

Per-book job items should store status, attempt count, last error, snapshot path, and timestamps so failed books can be retried or skipped without failing the entire job.

## Raw Snapshot Storage

Store raw scrape results under:

```text
data/scraped/libby/
```

Suggested filename pattern:

```text
{user_id}_{book_id}_{libby_title_id}_{timestamp}.html
```

or

```text
{user_id}_{book_id}_{libby_title_id}_{timestamp}.json
```

## Parser Strategy

Scraping and parsing should be separate.

- Scraper: retrieves and stores raw content
- Parser: reads raw content and extracts progress fields

This lets parser logic improve later without scraping again.

## Progress Interpretation

Initial inference rules:

```text
progress_percent >= 98 => completed
progress_percent > 0   => started
progress_percent == 0  => borrowed
unknown/null           => unknown
```

Manual status should be able to override inferred status.

When available, preserve more than percentage:

- position in seconds for audiobooks
- total seconds for audiobooks
- position in pages for ebooks or physical books
- total pages for ebooks or physical books
- observed timestamp

Exact completion dates may not always be available. Approximate dates are acceptable when clearly sourced, such as the latest borrow period or the date a scrape first observes completion.

## Failure Handling

Failures should be stored, not hidden.

Store:

- error message
- URL
- timestamp
- screenshot path, if available
- retry count

A single failed book should not fail the entire scrape job.

## Future Enhancements

- Headless mode after login is stable
- Screenshot capture on failure
- Per-library scrape configuration
- Retry with exponential backoff
- Scrape only active/recent loans
- User-configurable delay range
