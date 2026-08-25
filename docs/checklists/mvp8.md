# MVP 8 Checklist

## Goal

Add an explainable AI reading advisor that can summarize reading history and suggest useful next reads.

## Source

Derived from `docs/ROADMAP.md` MVP 8 - Agentic Recommendations, with continuity from MVP 5 series tracking, MVP 6 metadata enrichment, and MVP 7 analytics/recaps.

## Chunk 1 - Recommendation Scope And Safety

- [ ] Define recommendation types for MVP 8: series continuation, new series, genre exploration, author-adjacent, and backlog prioritization
- [ ] Define which local data the advisor can use
- [ ] Define what data should never be sent to an external model without explicit configuration
- [ ] Decide whether MVP 8 supports local-only LLM, OpenAI-compatible remote APIs, or both
- [ ] Define fallback behavior when no LLM provider is configured
- [ ] Define explainability requirements for each recommendation
- [ ] Define confidence or rationale fields for recommendations
- [ ] Define freshness rules for regenerating recommendations
- [ ] Document privacy and safety assumptions before implementation

## Chunk 2 - Recommendation Data Model

- [ ] Decide final schema for recommendation runs and individual recommendations
- [ ] Preserve prompt inputs or summarized context where safe and useful
- [ ] Preserve model/provider metadata for auditability
- [ ] Store recommendation type, title, author, series name, reasoning, and source data references
- [ ] Store accepted, dismissed, or saved user feedback if useful
- [ ] Add indexes for user, recommendation type, status, generated timestamp, and source
- [ ] Add Alembic migration
- [ ] Verify `alembic upgrade head`

## Chunk 3 - Reading History Summarizer

- [ ] Add service to summarize completed books by period
- [ ] Include favorite authors, genres, formats, and series from MVP 7 analytics
- [ ] Include recent reads/listens and recent abandons
- [ ] Include unread planned series entries and next unread books
- [ ] Include ratings and notes only when useful and safe
- [ ] Include format preferences and audiobook/page-length preferences
- [ ] Exclude raw Libby scraped HTML, browser profile data, session secrets, and private operational data
- [ ] Keep summarizer deterministic and testable
- [ ] Add tests for summary content and privacy exclusions

## Chunk 4 - Recommendation Service Interface

- [ ] Define provider-neutral recommendation request object
- [ ] Define provider-neutral recommendation response object
- [ ] Define provider interface for generating recommendations
- [ ] Implement local deterministic fallback provider for tests and no-LLM mode
- [ ] Implement optional local LLM provider if selected
- [ ] Implement optional OpenAI-compatible provider if selected
- [ ] Handle provider timeouts, malformed responses, empty responses, and rate limits safely
- [ ] Avoid blocking the UI indefinitely during generation
- [ ] Add tests for provider parsing and error handling

## Chunk 5 - Prompting And Output Contracts

- [ ] Create prompt template for series continuation suggestions
- [ ] Create prompt template for new series suggestions
- [ ] Create prompt template for genre exploration suggestions
- [ ] Create prompt template for general next-read suggestions
- [ ] Require structured output that can be parsed reliably
- [ ] Require recommendation reasoning tied to local reading history
- [ ] Ask the model to avoid inventing completed reading history
- [ ] Ask the model to label uncertainty when metadata is incomplete
- [ ] Add parser validation for structured recommendation output
- [ ] Add tests for prompt construction and response parsing

## Chunk 6 - Series Continuation Suggestions

- [ ] Identify active series with unread planned or owned entries
- [ ] Prefer next unread entries from local series tracking before model suggestions
- [ ] Include paused/abandoned series only when the user asks or settings allow it
- [ ] Explain why the series is being suggested
- [ ] Link recommendations back to local series pages and books when possible
- [ ] Avoid overwriting series status or wants-to-continue fields
- [ ] Add tests for active, paused, completed, and abandoned series cases

## Chunk 7 - New Series And Genre Exploration

- [ ] Generate new series suggestions from favorite genres, authors, ratings, and completion patterns
- [ ] Generate genre exploration suggestions adjacent to known preferences
- [ ] Avoid recommending books already owned/read when local matching can detect them
- [ ] Use local metadata cache/provider data only through safe summarized fields
- [ ] Include why each suggestion matches the user's history
- [ ] Include suggested starting point when recommending a series
- [ ] Add tests for duplicate avoidance and explanation quality fields

## Chunk 8 - Recommendation UI

- [ ] Add recommendations route and navigation entry
- [ ] Show latest recommendation runs
- [ ] Show recommendation cards grouped by type
- [ ] Show explanation for each recommendation
- [ ] Show source context such as related authors, genres, series, or recent reads
- [ ] Link to local matching books or series when available
- [ ] Add protected action to generate recommendations
- [ ] Add dismiss/save feedback controls if implemented
- [ ] Keep existing recommendations viewable in read-only mode
- [ ] Keep generation and feedback mutations admin-only
- [ ] Keep UI usable on desktop and mobile

## Chunk 9 - Configuration And Provider Setup

- [ ] Add configuration for recommendation provider selection
- [ ] Add configuration for local LLM base URL/model if supported
- [ ] Add configuration for OpenAI-compatible base URL/model/API key if supported
- [ ] Keep API keys out of committed files and logs
- [ ] Document no-provider fallback mode
- [ ] Surface clear UI message when generation is unavailable due to missing configuration
- [ ] Add tests for configured, missing, and invalid provider settings

## Chunk 10 - Jobs, Caching, And Regeneration

- [ ] Decide whether recommendation generation runs synchronously or as a job
- [ ] Store run status, started/finished timestamps, errors, and summary
- [ ] Avoid duplicate concurrent generation runs for the same user/type if needed
- [ ] Reuse recent recommendation runs unless user explicitly regenerates
- [ ] Preserve older recommendations for comparison unless explicitly deleted
- [ ] Add retry behavior or clear failed-run recovery path
- [ ] Add tests for run persistence, regeneration, and failure handling

## Chunk 11 - Privacy And Manual Data Protection

- [ ] Do not send raw import files, scrape snapshots, browser profiles, cookies, session secrets, or admin password to recommendation providers
- [ ] Do not overwrite books, reading events, series, genres, metadata cache, or recaps during recommendation generation
- [ ] Keep recommendations advisory only
- [ ] Require explicit user action before creating books, planned entries, or series from recommendations if such actions are added later
- [ ] Clearly label generated content and provider/model source
- [ ] Add tests for source-data preservation and permission boundaries

## Chunk 12 - Tests

- [ ] Test reading history summarizer
- [ ] Test privacy exclusions from summarized context
- [ ] Test recommendation provider interface
- [ ] Test deterministic fallback provider
- [ ] Test optional LLM provider configuration paths if implemented
- [ ] Test prompt construction and structured output parsing
- [ ] Test series continuation suggestions
- [ ] Test new series suggestions
- [ ] Test genre exploration suggestions
- [ ] Test duplicate owned/read avoidance
- [ ] Test recommendation UI permissions
- [ ] Test recommendation run persistence and errors
- [ ] Verify full `pytest` pass

## Chunk 13 - Documentation

- [ ] Update README with recommendation workflow
- [ ] Document provider configuration and no-provider fallback behavior
- [ ] Document privacy boundaries and what data may be sent to a model
- [ ] Document recommendation types and explanation fields
- [ ] Document regeneration behavior
- [ ] Update database documentation for recommendation tables
- [ ] Update architecture documentation for recommendation service and provider interface

## MVP 8 Done Criteria

- [ ] User can generate recommendation suggestions when a provider is configured or fallback mode is available
- [ ] User can view recommendations grouped by type
- [ ] Recommendations include explanations tied to local reading history
- [ ] User can get series continuation suggestions
- [ ] User can get new series suggestions
- [ ] User can get genre exploration suggestions
- [ ] Reading history summarizer excludes raw private files, cookies, secrets, and browser profile data
- [ ] Recommendation generation does not overwrite books, reading events, series, genres, metadata cache, or recaps
- [ ] Existing recommendations are viewable in read-only mode
- [ ] Recommendation generation is admin-only
- [ ] Provider/model configuration is documented
- [ ] Basic tests pass
