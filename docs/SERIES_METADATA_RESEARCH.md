# Series Metadata Research

MVP 6 keeps external provider series metadata suggestion-only. Open Library and Google Books enrichment must not create series, assign books to series, change positions, or replace MVP 5 manual series data.

Libby-derived series data is handled separately because Libby reading journey and series pages can expose stronger user-library context. Libby hints and series snapshots are still review-first: they are stored and previewed before any local series assignment or planned entry is created.

## Provider Findings

### Libby Reading Journey Pages

Libby reading journey pages can expose a series link for titles that belong to a Libby-known series. Example markup from a scraped journey page:

```html
<a class="halo" href="/shelf/series-503231/page-1"><strong><span role="text">Series</span></strong><cite><span role="text">#26 in Jack Reacher</span></cite></a>
```

This gives stronger local context than Open Library or Google Books for Libby-related books:

- Libby series key: `series-503231`
- Libby series URL: `/shelf/series-503231/page-1`
- Raw label: `#26 in Jack Reacher`
- Parsed position: `26`
- Parsed series name: `Jack Reacher`

MVP 6 behavior: use Libby journey-page series hints as the preferred series source for Libby-imported or Libby-scraped books, but still apply them only through an explicit admin confirmation workflow. Store the hint first, display it for review, and then let the user choose whether to match an existing local series or create a new one.

### Libby Series Pages

Libby series pages can list the works in a series and expose ordering, title, author, format, Libby title URLs, and collection labels. This makes them useful for populating an existing local series after the user has confirmed which local series the Libby page represents.

Important observed behavior:

- A series page may lazy-load items as the page scrolls.
- Explicit `books` and `audiobooks` filter URLs can expose entries not present in the initially loaded page.
- Ebook and audiobook rows for the same work may appear as separate tiles.
- Collections can appear as range labels such as `1-3 in series`.

MVP 6 behavior:

- Scrape Libby series pages at the series level, not once per book.
- Store raw snapshots locally in `libby_series_snapshots` with checksum, URL/key, parsed entry count, and raw parser context.
- Preview parsed unique works before applying changes.
- Collapse duplicate work rows across ebook/audiobook formats while showing combined format context.
- Match existing local books by Libby title ID first, then conservative title/author/format matching.
- Create planned entries for unmatched Libby works only after explicit admin confirmation.
- Preserve existing manual series entries, positions, planned entries, and notes.
- Track collection ranges with `series_books.position_end`.
- Count a completed collection as satisfying covered individual works while avoiding inflated progress totals when both collection and individual rows exist.

### Google Books

Google Books Volume API documents title, subtitle, authors, publisher, publication date, identifiers, page count, categories, ratings, image links, language, and access/sale metadata. It does not document a first-class series name, series ID, or series position field on public `volumeInfo` records.

Recommendation: do not use Google Books for automatic series assignment. At most, future work could inspect titles/subtitles/descriptions for possible series text and present it as a low-confidence suggestion.

### Open Library

Open Library Search API returns work/edition metadata and subjects, but its documented search response does not provide stable first-class series fields. Some Open Library Work JSON records can include a `series` array with a series key and position, and some subjects encode series-like labels such as `series:Harry_Potter`.

Risks:

- The Search API docs warn that returned fields are tied to Solr schema and are not guaranteed stable beyond common fields.
- Series data may exist at work level while ISBN lookup often resolves edition data first.
- Work-level series keys require additional fetches and a separate confidence model.
- Subject labels such as `series:*` are free-form and should not be treated as authoritative assignments.

Recommendation: Open Library can be a future source of series suggestions, but not an automatic source of local series records or assignments.

## MVP 6 Policy

- Do not auto-create `series` rows from external provider enrichment metadata.
- Do not auto-create or modify `series_books` rows from external provider enrichment metadata.
- Do not overwrite manual series assignments, planned entries, positions, notes, or continuation state.
- If future provider data indicates a likely series, show it as a candidate for user review only.
- Store raw provider responses in the metadata cache so future workflows can re-evaluate series hints without another provider call.
- For Libby-related books, prefer Libby journey-page series hints over external provider guesses because they include a Libby series page and title-specific position text.
- For Libby series population, require an existing local target series and explicit preview/apply confirmation before adding matched assignments or planned entries.
- Keep non-Libby books eligible for external metadata enrichment even when Libby series hints are unavailable.

## Future Workflow Recommendation

Future series-enrichment improvements should:

- Fetch work-level provider records only after an ISBN/title match has already been accepted.
- Normalize provider series candidates separately from local manual series names.
- Present suggested series name, provider, provider record key, proposed position, and confidence.
- Let the user choose an existing local series or create a new one explicitly.
- Require explicit confirmation before assigning a book or planned entry.
- Keep provider series hints auditable without changing MVP 5 manual-first data.
- Continue treating external provider series data as lower confidence than Libby journey/page data for Libby-related books.
