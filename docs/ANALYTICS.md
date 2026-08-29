# Analytics Definitions

MVP 7 analytics are derived from local source-of-truth records. Analytics must not mutate books, reading events, progress, metadata, or series records.

## Consumed Books

A consumed book is a user-owned `books` row that has evidence of completion.

Completion evidence, in priority order:

- A `reading_events` row with `event_type` in `completed` or `manually_completed`.
- A `books.completed_on` value.
- `books.status = completed` with `manual_progress_percent >= 98` or `book_progress.progress_percent >= 98`.

Archived books remain excluded from default analytics unless a future UI explicitly includes them.

Audiobook, ebook, and physical records remain distinct consumed records. If the same title exists in multiple formats, each format-specific record can count separately because the app tracks them separately.

## Period Boundaries

Analytics periods use local calendar dates from stored event/book dates.

- Month: first day through last day of the calendar month.
- Quarter: Jan-Mar, Apr-Jun, Jul-Sep, or Oct-Dec.
- Year: Jan 1 through Dec 31.
- All-time: no lower or upper date bound unless the user supplies one.

Period filters are inclusive at the date level. DateTime event values should be compared by their date portion for MVP 7 views.

## Completion Dates And Counts

Completed-book counts should be event-first.

Counting rules:

- Count each completion event for re-read/re-listen metrics.
- Count each book at most once per period for unique completed-book totals unless the view is explicitly about repeats.
- Use the earliest completion event in a period as that book's period placement when deduplicating unique completed books.
- If no completion event exists, use `books.completed_on`.
- If only completed status/progress exists, use the best available completion-like date in this order: `books.completed_on`, latest completed/progress event date, latest scraped progress observation date. If none exists, exclude it from date-bounded charts and include it only in undated/all-time summaries.

Manual correction events do not count as completions unless their `event_type` is `completed` or `manually_completed`.

## Re-Reads And Re-Listens

True re-read/re-listen counts are derived from completion events, not from Libby session counts.

Rules:

- First completion event for a book counts as the initial read/listen.
- Each additional completion event for the same book counts as a re-read or re-listen.
- Format determines label: audiobook repeats are re-listens; ebook/physical repeats are re-reads; unknown format uses repeat completion.
- Repeats should be period-filtered by the repeat completion event date.

## Prior Read/Listen Entries

Books consumed before tracking began should be represented as local reading events when possible.

Recommended MVP 7 representation:

- `reading_events.source = manual`
- `reading_events.event_type = manually_completed`
- `reading_events.event_date` set to the known prior completion date
- `reading_events.raw_data.prior_entry = true`
- Optional approximate-date context in `raw_data` if a future workflow supports year-only or month-only entries

Prior entries increment completed-book totals and repeat counts like other completion events. They must not rewrite Libby import events or scraped progress.

## Pages Read

Page totals use known page counts only.

Rules:

- Include completed ebook and physical records when `books.page_count` is known.
- Exclude audiobook records from page totals unless they also have a user-confirmed page count and a future UI explicitly asks to include them.
- Missing page counts contribute `0` pages and should be reported as missing-data counts where useful.
- Re-reads count pages again for repeat-oriented totals because the content was consumed again.
- Unique completed-book totals count pages once per book per period unless the view explicitly counts repeats.

## Audiobook Hours

Audiobook-hour totals use known durations only.

Rules:

- Include completed audiobook records when `books.audio_seconds` is known.
- If `books.audio_seconds` is missing, use `book_progress.total_seconds` only when it represents the title duration, not current listened position.
- Exclude ebook and physical records from audiobook-hour totals.
- Missing durations contribute `0` hours and should be reported as missing-data counts where useful.
- Re-listens count duration again for repeat-oriented totals.

## Partial Progress

Partial-progress summaries describe unfinished or abandoned books with known progress.

Include books when:

- `books.status` is `started`, `borrowed`, or `abandoned`; or
- latest inferred progress status is `started` or `borrowed`; and
- `manual_progress_percent` or `book_progress.progress_percent` is known and below the completion threshold.

Use manual progress before scraped progress when both exist. Progress at `98%` or higher is completion-level for MVP 7 and should not be reported as partial progress.

Partial summaries may include count of in-progress books, count of abandoned books with progress, average progress, pages-in-progress when total pages are known, and audiobook time-in-progress when total duration is known.

## Lifetime Enjoyed Time

Lifetime enjoyed time is separate from current-loan progress.

- `book_progress.position_seconds` is the current observed position when available.
- `book_progress.enjoyed_seconds` is Libby's reported lifetime enjoyed/listened/read time when available.
- Analytics should label enjoyed time as Libby-reported lifetime time, not as completed audiobook duration.
- Enjoyed time can exceed current-loan duration or exist without a true completion count.

## Libby Picked-Up Counts

Libby's `picked up this audiobook N times` text is a session/activity count, not a completed read/listen count.

MVP 7 must not:

- Treat picked-up count as read count.
- Treat picked-up count as re-listen count.
- Create completion events from picked-up count alone.

Picked-up count may be used later as a weak engagement signal, but repeat completion metrics must come from completion events or explicit prior entries.

## Source Preservation

Analytics and recaps are read-only derivations.

They must preserve:

- Libby imports and raw files
- Reading events
- Scraped progress and snapshots
- Metadata enrichment cache and run history
- Manual book edits
- Genres and series assignments
