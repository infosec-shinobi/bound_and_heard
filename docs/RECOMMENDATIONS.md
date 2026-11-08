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

MVP 8 should support no-provider fallback, optional OpenAI-compatible APIs, and opt-in browser-local inference.

Provider modes:

- `none`: No LLM provider is configured. The app uses deterministic local recommendations where possible and clearly labels that model-powered discovery is unavailable.
- `openai_compatible`: The app sends safe summarized context to an OpenAI-compatible chat/completions API configured by environment variables.
- `local_openai_compatible`: A local server such as Ollama, LM Studio, or another OpenAI-compatible endpoint may use the same provider interface when configured with a local base URL.
- `browser_local` (planned, Chunk 7.1): A small downloaded model runs on the viewing device in a browser worker. This is distinct from a local model server and requires explicit per-device consent.

MVP 8 does not need a provider-specific Ollama API implementation if the selected local runtime exposes an OpenAI-compatible endpoint. A separate native local provider can be added later if there is a concrete need.

## Browser-Local Inference Plan (MVP 8 Chunk 7.1)

This is planned work, not an implemented provider. Evaluate
[WebLLM](https://webllm.mlc.ai/docs/) with a Web Worker as the initial runtime
candidate. Prototype small quantized models before selecting a pinned runtime
and model: measure actual artifact size, memory needs, initialization/generation
time, context capacity, structured-output reliability, and recommendation quality
on target devices. Review model licensing. Small models should primarily rank or
explain supplied bibliographic candidates; they must not be trusted to invent
accurate book catalogs or reading history.

### Consent And Device Lifecycle

- Offer an unchecked **Enable on-device AI recommendations** checkbox and an
  explicit **Download model** action. Disclose model identity, expected download
  size/source, device requirements, and data flow before authorization.
- No model download or inference initialization occurs before consent. Consent
  belongs to this browser/device and model version, not every device accessing
  the server. A changed model requires renewed download authorization.
- Detect WebGPU, secure context, and required GPU capabilities. HTTPS is generally
  required for homelab access; localhost is a special case. Plain
  `http://SERVER_IP` should show setup guidance rather than attempting generation.
- Show loading/download/generation progress and allow cancellation. Run inference
  in a worker so the UI remains responsive. Provide clear recovery for download,
  storage, GPU-memory, and generation failures.
- Model artifacts may persist in browser-origin storage after the tab/session
  closes. Explain cache reuse and possible browser eviction, and provide
  **Remove downloaded model**. Do not imply the model stays loaded after closing
  the page or that browser caching guarantees permanent/offline availability.
- The model runs on the device displaying the app, not the Bound & Heard host.
  Unsupported devices, declined consent, and failures retain deterministic local
  suggestions. Never silently switch to a remote inference provider.

### Execution And Trust Boundaries

1. An admin initiates generation. The backend supplies the existing allowlisted
   history, source catalog, prompts/output schema, and bounded safe candidates.
   Browser-local mode must not expose raw files, notes, operational secrets, or
   provider credentials to the client.
2. The browser worker performs inference locally. Model downloads may contact an
   external artifact host, revealing normal request metadata, but reading history
   and prompts must not be sent to that host or any remote inference service.
   Bundle/pin trusted runtime assets and model sources; avoid third-party runtime
   scripts or telemetry that could access reading history.
3. Local series tracking remains authoritative, including continuation intent and
   opt-in status rules. Browser generation does not overwrite source records.
4. Generated results may be previewed in the browser. Saving is a separate
   protected submission to the Bound & Heard server, not an external model host.
   Treat submitted content, IDs, provider labels, and evidence as untrusted.
5. Before persistence, the backend validates schema, requested type/count,
   references against server-retained generation context, duplicate matching, and
   local IDs resolved from trusted records. Do not accept a browser-supplied
   history/catalog as proof of evidence. Record provider/model provenance without
   implying that the server can attest which model actually executed on a client.
6. Saved runs follow the normal recommendation freshness/history rules; artifact
   caching is separate from recommendation caching. Interrupted browser sessions
   must not appear as successfully completed runs.

Tests should cover consent/download gating, capabilities, cancellation, cache
removal, privacy/network boundaries, tampered output/context, and admin checks.
Include real-browser/device smoke tests alongside mocked unit tests. UI controls,
configuration, and run persistence integrate with Chunks 8–10.

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
- `status`: User feedback state such as `active`, `saved`, or `dismissed`.

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

## Persistence Model

MVP 8 stores recommendation history in two tables:

- `recommendation_runs`: one row per generation attempt, including status, provider/model metadata, safe input summary, run summary, timestamps, and errors.
- `recommendations`: one row per individual recommendation, including type, status, local book/series links, explanation fields, confidence, source context, generated timestamp, and provider payload.

The run-level `input_summary` is intentionally a safe summary, not a raw prompt dump by default. It may include enough structured context to explain why a run produced recommendations, but it must follow the excluded-data rules above.

## Reading History Summary Contract

`app.services.recommendation_summary.summarize_reading_history` builds the safe local context that later recommendation providers can consume.

The summary includes:

- Period start/end.
- Completed-book totals, pages read, audiobook seconds, and lifetime enjoyed audiobook seconds.
- Favorite authors, genres, formats, and series derived from analytics-safe completed-book data.
- Recent completed books and recent abandons.
- Rating aggregates, highly rated items, typical page count, and typical audiobook duration.
- Active/paused/unknown series, next unread entries, and planned unread entries.
- Safety flags confirming raw imports, scrape snapshots, browser profiles, secrets, and raw provider responses are excluded.

The summary deliberately excludes:

- `reading_events.raw_data`.
- Raw import or scrape file paths and contents.
- Browser profile paths and session state.
- Environment values, provider keys, admin password, session secret, and deployment details.
- Full notes by default.

Bounded note excerpts are available only when `include_note_summaries=True`. This is intended for a later explicit user setting or reviewed prompt path, not as the default provider context.

## Recommendation Service Interface (Chunk 4)

`app.services.recommendation_providers` defines validated provider-neutral
`RecommendationRequest`, `RecommendationSuggestion`, and `RecommendationResponse`
objects plus the async `RecommendationProvider` protocol. Suggestions use
`reasoning` (matching the persisted model) for the human-readable reason.
Provider/model provenance belongs to the response; user feedback and persistence
are separate concerns.

Pass the result of `summarize_reading_history` as the request's `history`.
The typed `HistoryContext` projects nested fields onto an allowlist of favorites,
recent books, rating/length preferences, and series context. Unknown fields,
including note excerpts, raw payloads, and operational metadata, are discarded.
It does not attempt to sanitize secrets manually entered into bibliographic text.

`app.services.recommendation_service.generate_recommendations` is an awaitable,
non-mutating service entry point. Without a provider it uses
`DeterministicRecommendationProvider`, which returns stable next-unread suggestions
from active series unless continuation intent is explicitly false. It supports
series continuation and series-backed backlog requests; it does not invent
discovery suggestions. Broader backlog ranking and discovery remain later work.

Optional adapters are constructed explicitly at this stage:

- `OpenAICompatibleRecommendationProvider(base_url=..., model=..., api_key=...)`
  calls `{base_url}/chat/completions`; include `/v1` in the base URL when required.
- `LocalOpenAICompatibleRecommendationProvider` uses the same API, allows no key,
  and requires a loopback hostname (`localhost`, `127.0.0.1`, or `::1`). For a
  LAN/container endpoint, explicitly use the remote-compatible adapter instead.

The adapters request a JSON object containing a `recommendations` list, validate
every suggestion, enforce requested type/count, and reject malformed output as a
whole. An empty list is `no_results`. Model-supplied local IDs are cleared rather
than trusted as database links; deterministic suggestions retain known local IDs.
Local matching of discovery results belongs to a later chunk.

Async HTTP uses a 30-second adapter deadline by default, plus a 35-second service
deadline (both configurable up to 120 seconds). Responses are capped at 1 MB;
redirects and automatic retries are disabled. Failures return sanitized statuses
(`timeout`, `rate_limited`, `malformed`, or `failed`) without raw response bodies,
exception strings, keys, or prompt logging. Cancellation propagates to callers.
Configured-provider failures are surfaced rather than silently replaced by local
results. Awaiting generation does not block the event loop; UI wiring, environment
configuration, jobs, and run persistence remain later chunks.

Tests in `tests/test_recommendation_providers.py` use mocked transports, not live
model endpoints. Chunk 4 verification: full suite, **458 passed**.

## Prompting And Output Contracts (Chunk 5)

`app.services.recommendation_prompts` builds separate system instructions for
series continuation, new series, genre exploration, author-adjacent, backlog,
and general next-read requests. Shared instructions require advisory-only output,
history-based reasoning, no invented completions, and explicit caveats/lower
confidence when metadata or evidence is incomplete. History values remain in the
user message and are explicitly treated as untrusted data, not instructions.

The user message includes the allowlisted history, requested type/count, and a
request-local `source_catalog`. Catalog keys such as `favorites.genres:0` or
`series.active_or_paused:0` identify individual supplied facts. Each model
suggestion must cite only exact catalog keys in `source_context`; nonexistent
references reject the whole response. Empty history has no valid evidence keys.
These references are request-local evidence, not trusted database links.

Providers still request JSON-object mode and include the Pydantic output schema
in the system prompt. Parsing enforces types, nonempty titles/reasoning, confidence,
source references, requested type/count, and unknown-field rejection. New-series
suggestions additionally require a nonblank series name and starting point.
Malformed output is rejected without logging or returning raw model content.
An empty recommendations list remains a valid `no_results` response.

Evidence validation proves references exist, not that the model's prose or
external bibliographic claims are accurate. Caveat quality and semantic reasoning
remain model instructions rather than guarantees; discovery matching and local
duplicate detection remain later chunks.

Tests in `tests/test_recommendation_prompts.py` cover every template, privacy,
determinism, untrusted history placement, evidence validation, uncertainty fields,
and starting-point requirements. Chunk 5 verification: full suite, **475 passed**.

## Series Continuation (Chunk 6)

The history summarizer translates stored continuation intent (`yes`, `no`,
`unknown`) into `true`, `false`, or `null` for the provider contract. It includes
abandoned series separately under `series.abandoned`; completed series are never
continuation candidates. Next-unread selection orders numbered entries before
unnumbered entries and skips completed books, including undated completion status
or near-complete progress evidence. Archived books and books belonging to another
user are excluded from these local series candidates.

`RecommendationRequest` accepts `include_paused_series` and
`include_abandoned_series`, both false by default. Callers can explicitly opt in
without changing stored series status or intent. An explicit `no` always vetoes
a suggestion; unknown intent is allowed for otherwise eligible series but is
disclosed as a caveat. Unknown/completed statuses remain excluded even with flags.
These request flags are service-level controls; UI/settings wiring remains later work.

`generate_recommendations` treats local tracking as authoritative:

- Explicit `series_continuation` requests use deterministic local results only,
  including `no_results` when there is no eligible next unread entry. No model is called.
- General next-read requests return eligible local continuation results first,
  up to the requested limit, without calling a model or mixing provenance.
- When general requests have no local candidates, a configured model can provide
  discovery results, but model-generated `series_continuation` items are removed.
- Explicit discovery requests continue to use the configured provider even if
  local series candidates exist.

Active series rank before opted-in paused/abandoned series, then by name and ID.
Each suggestion includes completion counts, status, continuation intent, planned
versus local entry, position when known, evidence references, and a starting point.
Unknown positions/intent and opted-in non-active status lower confidence and add
caveats. Local suggestions preserve trusted `local_series_id` and `local_book_id`
for `/series/{id}` and `/books/{id}` links; planned entries have no book link.
Rendering these links belongs to the recommendation UI chunk.

Generation does not modify books, events, series entries, status, or intent.
`tests/test_series_recommendations.py` covers database-to-request integration,
status/intent policies, completion evidence, user/archive exclusions, deterministic
ordering/limits, local precedence, IDs, and source preservation.
Chunk 6 verification: full suite, **499 passed**.

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
