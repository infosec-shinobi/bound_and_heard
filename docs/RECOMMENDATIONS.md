# Recommendation Advisor Definitions

MVP 8 adds an explainable recommendation advisor that uses local reading history to suggest useful next reads. Recommendations are advisory only: generation must not modify books, reading events, series, genres, metadata cache rows, recaps, imports, scrape jobs, or source files.

## Recommendation Types

MVP 8 supports these recommendation types:

- `series_continuation`: Suggest the next unread item in a locally tracked series the user appears to want to continue.
- `new_series`: Suggest a new series that matches the user's completed books, favorite genres, authors, formats, ratings, or series completion patterns.
- `genre_exploration`: Suggest books or series in adjacent genres that broaden the user's reading without ignoring known preferences.
- `author_adjacent`: Suggest books or authors similar to authors the user frequently completes, rates highly, or repeatedly returns to.
- `backlog_prioritization`: Suggest books already in the local library, want-to-read list, borrowed list, or planned series entries that are good candidates to read next.

MVP 8 should prefer local deterministic recommendations when local data is enough, especially for series continuation and backlog prioritization. Model-generated suggestions are most useful for new series, genre exploration, and author-adjacent discovery.

## Allowed Local Data

The advisor may use summarized, structured fields from local records:

- Book title, subtitle, author, format, status, source, rating, page count, audio duration, published year, publisher, ISBNs, cover URL, and metadata source.
- Completion, start, abandon, borrow, and manual correction dates from normalized reading events.
- Progress summary fields such as current percent, pages, seconds, inferred status, lifetime enjoyed seconds, and repeat-count heuristics.
- Genre labels and normalized provider categories already stored in the database.
- Series names, statuses, continuation intent, book order, planned entries, next unread entries, and local series membership.
- Analytics summaries such as favorite authors, favorite genres, format mix, completion cadence, pages read, audiobook time, repeats, recent completions, and recent abandons.
- Recap summary fields that are already generated from safe normalized data.
- Metadata cache summary fields only when reduced to safe bibliographic facts. Raw provider responses should not be sent to a model by default.
- User display name only when useful for UI labeling; it is not needed for model prompts by default.

The summarizer should prefer derived aggregates and short source references over raw rows. For example, use "completed 8 audiobooks by Author X" rather than sending every raw event payload.

## Data Excluded From External Models

The following must never be sent to an external model unless a future explicit setting and review UI allows it:

- Raw Libby JSON import files under `data/imports/`.
- Raw scrape snapshots under `data/scraped/`, including HTML, text captures, screenshots, downloaded assets, and Libby journey pages.
- Browser profile data under `data/browser/`, including cookies, local storage, cache files, and session state.
- Admin password, session secret, provider API keys, `.env` values, Docker secrets, database URLs containing credentials, and other operational secrets.
- Raw metadata provider responses from the metadata cache.
- Raw recap artifacts or exported files when they include more detail than the safe summarized fields needed for recommendations.
- Local filesystem paths, hostnames, deployment details, logs, stack traces, or debug output.
- Full personal notes by default. Short note-derived preference summaries may be considered later only with an explicit setting.

MVP 8 should implement privacy by construction: provider prompts should be built from an allowlist of safe summary fields, not by filtering a broad serialized object.

## Provider Support

MVP 8 should support both no-provider fallback and optional OpenAI-compatible remote APIs.

Provider modes:

- `none`: No LLM provider is configured. The app uses deterministic local recommendations where possible and clearly labels that model-powered discovery is unavailable.
- `openai_compatible`: The app sends safe summarized context to an OpenAI-compatible chat/completions API configured by environment variables.
- `local_openai_compatible`: A local server such as Ollama, LM Studio, or another OpenAI-compatible endpoint may use the same provider interface when configured with a local base URL.

MVP 8 does not need a provider-specific Ollama API implementation if the selected local runtime exposes an OpenAI-compatible endpoint. A separate native local provider can be added later if there is a concrete need.

## No-Provider Fallback

When no LLM provider is configured, the advisor should remain useful:

- Generate series continuation recommendations from local series tracking.
- Generate backlog prioritization recommendations from locally owned, borrowed, started, want-to-read, and planned entries.
- Show a clear UI message that new-series, genre-exploration, and author-adjacent discovery are limited without a configured provider.
- Store recommendation runs as deterministic fallback runs if the data model supports persistence in the current chunk.
- Never fail the whole recommendations page because provider configuration is missing.

Fallback recommendations should be explicitly labeled as local deterministic suggestions rather than AI-generated recommendations.

## Explainability Requirements

Each recommendation must include enough explanation to make it auditable and useful.

Required fields for every recommendation:

- `recommendation_type`: One of the supported type values.
- `title`: Book, series, author, or backlog item title.
- `author`: Author when known or applicable.
- `series_name`: Series name when known or applicable.
- `reason`: Short human-readable explanation.
- `source_context`: Safe references to local facts that motivated the suggestion.
- `confidence`: `high`, `medium`, or `low`.
- `provider`: `local`, `openai_compatible`, or another provider key.
- `model`: Model name when a model is used.

Recommended optional fields:

- `local_book_id`: Matching local book ID when the suggestion maps to an existing book.
- `local_series_id`: Matching local series ID when the suggestion maps to an existing series.
- `suggested_starting_point`: First book or next book when recommending a series.
- `format_hint`: Ebook, audiobook, physical, or unknown when relevant.
- `rationale_tags`: Short labels such as `favorite_author`, `series_next`, `genre_match`, `high_rating`, `recent_interest`, or `backlog`.
- `caveats`: Uncertainty notes, missing metadata, or duplicate-match warnings.

## Type-Specific Explanation Rules

`series_continuation` recommendations should explain:

- The local series status and continuation intent.
- The next unread planned or owned entry.
- Completed count versus total known entries.
- Any caveat when positions are missing or the series is paused/unknown.

`new_series` recommendations should explain:

- Which favorite genres, authors, ratings, formats, or completed series made the series relevant.
- The suggested starting point.
- Whether the app found any local duplicate or existing copy.

`genre_exploration` recommendations should explain:

- Which current preference the suggestion is adjacent to.
- What is new or exploratory about it.
- Why it is not too far outside known preferences.

`author_adjacent` recommendations should explain:

- Which local authors or books are being used as anchors.
- What similarity is being claimed.
- Whether the recommendation is based on local data or model knowledge.

`backlog_prioritization` recommendations should explain:

- Why this local item should move up the queue.
- Whether it is borrowed, started, planned in a series, highly rated by metadata, short/long enough for current preferences, or related to recent activity.
- The local book or series link when available.

## Confidence Rules

Confidence is an advisory quality signal, not a guarantee.

- `high`: Strong local evidence, such as the next unread active series entry or a backlog item matching multiple recent/favorite signals.
- `medium`: Reasonable local evidence or model suggestion tied to clear preferences, but with incomplete metadata or no direct local match.
- `low`: Sparse evidence, exploratory suggestion, uncertain duplicate matching, incomplete author/title metadata, or provider uncertainty.

The app should not hide low-confidence recommendations by default, but the UI should label them clearly.

## Freshness And Regeneration

Recommendation freshness should be based on source data changes and explicit user intent.

Default rules:

- Reuse the latest successful recommendation run for read-only viewing.
- Let an admin explicitly regenerate recommendations.
- Treat recommendations as stale when new imports, completed events, ratings, series changes, metadata enrichment, or backlog/status changes happen after the run was generated.
- A recommendation run generated within the last 24 hours may be reused unless the user explicitly chooses to regenerate or source data changed materially.
- Preserve previous runs for audit/history until a future cleanup workflow is added.

Regeneration must be admin-only. Viewing existing recommendations may remain read-only.

## Privacy And Safety Assumptions

MVP 8 assumes a local-first, single-user deployment protected by the existing admin password model.

Safety requirements:

- Build prompts from safe summary objects, not raw database dumps or files.
- Do not log prompts or model responses if they may contain reading history, unless a future explicit debug setting is added.
- Do not include secrets or filesystem paths in provider errors shown to the UI.
- Keep recommendation generation advisory and non-mutating.
- Require explicit user action before any future workflow creates books, planned entries, series, or metadata from a recommendation.
- Label generated content with provider/model source.
- Keep no-provider mode functional so the app does not require external AI services.
