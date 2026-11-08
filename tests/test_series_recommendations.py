import asyncio
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Book, BookProgress, ReadingEvent, Series, SeriesBook, User
from app.services.recommendation_providers import RecommendationRequest, RecommendationResponse, RecommendationSuggestion
from app.services.recommendation_service import generate_recommendations
from app.services.recommendation_summary import summarize_reading_history


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([User(id=1, display_name="Reader"), User(id=2, display_name="Other")])
        session.commit()
        yield session
    engine.dispose()


def series_with_entry(db, *, status="active", intent="yes", planned=False, position=2):
    series = Series(user_id=1, name="Local Saga", status=status, wants_to_continue=intent)
    db.add(series)
    db.flush()
    book = None
    if not planned:
        book = Book(user_id=1, title="Next Book", format="ebook", status="want_to_read")
        db.add(book)
        db.flush()
    db.add(SeriesBook(series_id=series.id, book_id=book.id if book else None,
                      planned_title="Planned Book" if planned else None, position=position))
    db.commit()
    return series, book


def generate(db, *, provider=None, **options):
    request = RecommendationRequest(history=summarize_reading_history(db, user_id=1), **options)
    before = request.model_dump()
    result = asyncio.run(generate_recommendations(request, provider=provider))
    assert request.model_dump() == before
    return result


@pytest.mark.parametrize("planned", [False, True])
def test_active_series_links_and_explanations_without_source_mutation(db, planned):
    series, book = series_with_entry(db, planned=planned)
    result = generate(db, recommendation_type="series_continuation")
    assert result.status == "succeeded"
    item = result.recommendations[0]
    assert item.local_series_id == series.id
    assert item.local_book_id == (book.id if book else None)
    assert item.title == (book.title if book else "Planned Book")
    assert item.suggested_starting_point == item.title
    assert "0 of 1" in item.reasoning
    assert "continuation intent is yes" in item.reasoning
    assert "position 2" in item.reasoning
    assert item.source_context == ["series.active_or_paused:0"]
    assert item.confidence == "high"
    assert not db.new and not db.dirty and not db.deleted
    db.expire_all()
    assert db.get(Series, series.id).status == "active"
    assert db.get(Series, series.id).wants_to_continue == "yes"
    assert len(db.scalars(select(SeriesBook)).all()) == 1


@pytest.mark.parametrize("status", ["paused", "abandoned", "completed", "unknown"])
def test_non_active_series_excluded_by_default(db, status):
    series_with_entry(db, status=status)
    assert generate(db).status == "no_results"


@pytest.mark.parametrize("status,flag", [("paused", "include_paused_series"), ("abandoned", "include_abandoned_series")])
def test_paused_and_abandoned_require_explicit_opt_in(db, status, flag):
    series, _ = series_with_entry(db, status=status)
    item = generate(db, **{flag: True}).recommendations[0]
    assert item.local_series_id == series.id
    assert item.confidence == "medium"
    assert any(status in caveat for caveat in item.caveats)
    series.wants_to_continue = "no"
    db.commit()
    assert generate(db, **{flag: True}).status == "no_results"


@pytest.mark.parametrize("intent", ["yes", "no", "unknown"])
def test_database_intent_mapping_and_uncertainty(db, intent):
    series_with_entry(db, intent=intent, position=None)
    result = generate(db)
    if intent == "no":
        assert result.status == "no_results"
    else:
        item = result.recommendations[0]
        assert "Series position is unknown." in item.caveats
        assert ("Continuation intent is unknown." in item.caveats) == (intent == "unknown")


@pytest.mark.parametrize("evidence", ["status", "date", "event", "progress"])
def test_completed_entries_are_skipped_even_without_dated_events(db, evidence):
    series, book = series_with_entry(db)
    if evidence == "status":
        book.status = "completed"
    elif evidence == "date":
        book.completed_on = date(2026, 1, 1)
    elif evidence == "event":
        db.add(ReadingEvent(user_id=1, book_id=book.id, source="manual", event_type="manually_completed",
                            event_date=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    else:
        db.add(BookProgress(user_id=1, book_id=book.id, source="manual", progress_percent=100))
    db.add(SeriesBook(series_id=series.id, planned_title="Later Book", position=3))
    db.commit()
    item = generate(db).recommendations[0]
    assert item.title == "Later Book"
    assert "1 of 2" in item.reasoning


@pytest.mark.parametrize("excluded", ["archived", "other_user"])
def test_ineligible_local_books_not_exposed(db, excluded):
    series, book = series_with_entry(db)
    if excluded == "archived":
        book.archived_at = datetime.now(timezone.utc)
    else:
        book.user_id = 2
    db.add(SeriesBook(series_id=series.id, planned_title="Safe Next", position=3))
    db.commit()
    item = generate(db).recommendations[0]
    assert item.title == "Safe Next"
    assert item.local_book_id is None


class DiscoveryProvider:
    name = "test"
    model = "test"

    def __init__(self):
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        return RecommendationResponse(provider=self.name, model=self.model, status="no_results")


@pytest.mark.parametrize("kind", [None, "series_continuation"])
def test_local_next_unread_wins_over_configured_model(db, kind):
    series_with_entry(db)
    provider = DiscoveryProvider()
    assert generate(db, provider=provider, recommendation_type=kind).provider == "local"
    assert provider.calls == 0


def test_no_model_continuation_when_local_series_is_ineligible(db):
    series_with_entry(db, status="paused")
    provider = DiscoveryProvider()
    assert generate(db, provider=provider, recommendation_type="series_continuation").status == "no_results"
    assert provider.calls == 0
    generate(db, provider=provider)
    assert provider.calls == 1


def test_explicit_discovery_still_uses_model_with_local_candidates(db):
    series_with_entry(db)
    provider = DiscoveryProvider()
    generate(db, provider=provider, recommendation_type="new_series")
    assert provider.calls == 1


def test_model_cannot_bypass_series_policy_in_general_results(db):
    class InventingProvider(DiscoveryProvider):
        async def generate(self, request):
            return RecommendationResponse(provider=self.name, status="succeeded", recommendations=[
                RecommendationSuggestion(recommendation_type="series_continuation", title="Invented Next",
                    reasoning="Invented", confidence="high", source_context=["series.active_or_paused:0"]),
            ])

    series_with_entry(db, status="paused")
    result = generate(db, provider=InventingProvider())
    assert result.status == "no_results"
    assert not result.recommendations


def test_all_entries_completed_returns_no_results(db):
    _, book = series_with_entry(db)
    book.status = "completed"
    db.commit()
    assert generate(db).status == "no_results"


def test_user_scope_ordering_and_limit_are_deterministic(db):
    paused, _ = series_with_entry(db, status="paused")
    paused.name = "A Paused Saga"
    active, _ = series_with_entry(db, planned=True)
    active.name = "Z Active Saga"
    other, _ = series_with_entry(db, planned=True)
    other.user_id = 2
    other.name = "Other User's Saga"
    db.commit()
    first = generate(db, include_paused_series=True, max_results=1)
    second = generate(db, include_paused_series=True, max_results=1)
    assert first == second
    assert [item.local_series_id for item in first.recommendations] == [active.id]
    assert len(generate(db, include_paused_series=True).recommendations) == 2
