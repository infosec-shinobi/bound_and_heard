from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, Recommendation, RecommendationRun, Series, User


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_recommendation_run_preserves_safe_input_and_provider_metadata() -> None:
    session_factory = make_session_factory()

    with session_factory() as db_session:
        db_session.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
        run = RecommendationRun(
            user_id=DEFAULT_LOCAL_USER_ID,
            recommendation_type="all",
            status="completed",
            provider="local",
            model=None,
            source="deterministic_fallback",
            started_at=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 10, 8, 12, 1, tzinfo=timezone.utc),
            generated_at=datetime(2026, 10, 8, 12, 1, tzinfo=timezone.utc),
            summary={"recommendation_count": 1},
            input_summary={"favorite_genres": ["Fantasy"], "raw_files_included": False},
            provider_metadata={"mode": "none"},
        )
        db_session.add(run)
        db_session.commit()

        saved = db_session.get(RecommendationRun, run.id)

        assert saved is not None
        assert saved.user.display_name == "Local User"
        assert saved.status == "completed"
        assert saved.summary == {"recommendation_count": 1}
        assert saved.input_summary == {"favorite_genres": ["Fantasy"], "raw_files_included": False}
        assert saved.provider_metadata == {"mode": "none"}
        assert saved.created_at is not None
        assert saved.updated_at is not None


def test_recommendation_stores_explainable_fields_feedback_state_and_local_links() -> None:
    session_factory = make_session_factory()

    with session_factory() as db_session:
        db_session.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
        book = Book(
            user_id=DEFAULT_LOCAL_USER_ID,
            title="Queued Book",
            primary_author_name="Test Author",
            format="ebook",
            status="want_to_read",
        )
        series = Series(user_id=DEFAULT_LOCAL_USER_ID, name="Tracked Series", status="active", wants_to_continue="yes")
        db_session.add_all([book, series])
        db_session.flush()
        run = RecommendationRun(
            user_id=DEFAULT_LOCAL_USER_ID,
            recommendation_type="backlog_prioritization",
            status="completed",
            provider="local",
            source="deterministic_fallback",
        )
        db_session.add(run)
        db_session.flush()
        recommendation = Recommendation(
            run_id=run.id,
            user_id=DEFAULT_LOCAL_USER_ID,
            local_book_id=book.id,
            local_series_id=series.id,
            recommendation_type="backlog_prioritization",
            status="saved",
            source="deterministic_fallback",
            provider="local",
            confidence="high",
            title="Queued Book",
            author="Test Author",
            series_name="Tracked Series",
            suggested_starting_point="Queued Book",
            format_hint="ebook",
            reasoning="This is the next unread active series entry already in the backlog.",
            source_context={"series_status": "active", "wants_to_continue": "yes"},
            rationale_tags=["series_next", "backlog"],
            caveats=[],
            payload={"rank": 1},
        )
        db_session.add(recommendation)
        db_session.commit()

        saved = db_session.get(Recommendation, recommendation.id)

        assert saved is not None
        assert saved.run.recommendations == [saved]
        assert saved.user.display_name == "Local User"
        assert saved.local_book == book
        assert saved.local_series == series
        assert saved.status == "saved"
        assert saved.confidence == "high"
        assert saved.source_context == {"series_status": "active", "wants_to_continue": "yes"}
        assert saved.rationale_tags == ["series_next", "backlog"]
        assert saved.caveats == []
        assert saved.payload == {"rank": 1}
        assert saved.generated_at is not None


def test_recommendation_model_indexes_support_expected_filters() -> None:
    session_factory = make_session_factory()
    inspector = inspect(session_factory.kw["bind"])

    run_indexes = {index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("recommendation_runs")}
    recommendation_indexes = {index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("recommendations")}

    assert run_indexes["ix_recommendation_runs_user_id"] == ("user_id",)
    assert run_indexes["ix_recommendation_runs_recommendation_type"] == ("recommendation_type",)
    assert run_indexes["ix_recommendation_runs_status"] == ("status",)
    assert run_indexes["ix_recommendation_runs_generated_at"] == ("generated_at",)
    assert run_indexes["ix_recommendation_runs_source"] == ("source",)
    assert recommendation_indexes["ix_recommendations_user_id"] == ("user_id",)
    assert recommendation_indexes["ix_recommendations_recommendation_type"] == ("recommendation_type",)
    assert recommendation_indexes["ix_recommendations_status"] == ("status",)
    assert recommendation_indexes["ix_recommendations_generated_at"] == ("generated_at",)
    assert recommendation_indexes["ix_recommendations_source"] == ("source",)
    assert recommendation_indexes["ix_recommendations_local_book_id"] == ("local_book_id",)
    assert recommendation_indexes["ix_recommendations_local_series_id"] == ("local_series_id",)


def test_recommendation_tables_are_registered_in_metadata() -> None:
    assert "recommendation_runs" in Base.metadata.tables
    assert "recommendations" in Base.metadata.tables
