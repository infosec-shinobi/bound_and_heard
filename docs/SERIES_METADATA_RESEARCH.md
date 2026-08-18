# Series Metadata Research

MVP 6 keeps external series metadata suggestion-only. Enrichment must not create series, assign books to series, change positions, or replace MVP 5 manual series data.

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

Recommendation: use Libby journey-page series hints as the preferred series source for Libby-imported or Libby-scraped books, but still apply them only through an explicit admin confirmation workflow. Store the hint first, display it for review, and then let the user choose whether to match an existing local series or create a new one.

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

- Do not auto-create `series` rows from enrichment metadata.
- Do not auto-create or modify `series_books` rows from enrichment metadata.
- Do not overwrite manual series assignments, planned entries, positions, notes, or continuation state.
- If future provider data indicates a likely series, show it as a candidate for user review only.
- Store raw provider responses in the metadata cache so future workflows can re-evaluate series hints without another provider call.
- For Libby-related books, prefer Libby journey-page series hints over external provider guesses because they include a Libby series page and title-specific position text.
- Keep non-Libby books eligible for external metadata enrichment even when Libby series hints are unavailable.

## Future Workflow Recommendation

A future series-enrichment workflow should:

- Parse Libby series links and labels during Libby journey scraping.
- Store Libby series hints separately from confirmed local series assignments.
- Display `Libby suggests #N in Series Name` on book detail and import review pages.
- Offer an admin-only apply action that matches an existing local series by normalized name before creating a new one.
- Fetch work-level provider records only after an ISBN/title match has already been accepted.
- Normalize provider series candidates separately from local manual series names.
- Present suggested series name, provider, provider record key, proposed position, and confidence.
- Let the user choose an existing local series or create a new one explicitly.
- Require explicit confirmation before assigning a book or planned entry.
- Keep provider series hints auditable without changing MVP 5 manual-first data.
