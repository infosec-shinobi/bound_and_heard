"""add recommendations

Revision ID: 20261008_0013
Revises: 20260831_0012
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261008_0013"
down_revision: str | None = "20260831_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("recommendation_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("input_summary", sa.JSON(), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recommendation_runs_created_at"), "recommendation_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_error_code"), "recommendation_runs", ["error_code"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_finished_at"), "recommendation_runs", ["finished_at"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_generated_at"), "recommendation_runs", ["generated_at"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_model"), "recommendation_runs", ["model"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_provider"), "recommendation_runs", ["provider"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_recommendation_type"), "recommendation_runs", ["recommendation_type"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_source"), "recommendation_runs", ["source"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_started_at"), "recommendation_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_status"), "recommendation_runs", ["status"], unique=False)
    op.create_index(op.f("ix_recommendation_runs_user_id"), "recommendation_runs", ["user_id"], unique=False)

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("local_book_id", sa.Integer(), nullable=True),
        sa.Column("local_series_id", sa.Integer(), nullable=True),
        sa.Column("recommendation_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("author", sa.String(length=300), nullable=True),
        sa.Column("series_name", sa.String(length=300), nullable=True),
        sa.Column("suggested_starting_point", sa.String(length=500), nullable=True),
        sa.Column("format_hint", sa.String(length=50), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("source_context", sa.JSON(), nullable=True),
        sa.Column("rationale_tags", sa.JSON(), nullable=True),
        sa.Column("caveats", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["local_book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["local_series_id"], ["series.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["recommendation_runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recommendations_confidence"), "recommendations", ["confidence"], unique=False)
    op.create_index(op.f("ix_recommendations_created_at"), "recommendations", ["created_at"], unique=False)
    op.create_index(op.f("ix_recommendations_format_hint"), "recommendations", ["format_hint"], unique=False)
    op.create_index(op.f("ix_recommendations_generated_at"), "recommendations", ["generated_at"], unique=False)
    op.create_index(op.f("ix_recommendations_local_book_id"), "recommendations", ["local_book_id"], unique=False)
    op.create_index(op.f("ix_recommendations_local_series_id"), "recommendations", ["local_series_id"], unique=False)
    op.create_index(op.f("ix_recommendations_model"), "recommendations", ["model"], unique=False)
    op.create_index(op.f("ix_recommendations_provider"), "recommendations", ["provider"], unique=False)
    op.create_index(op.f("ix_recommendations_recommendation_type"), "recommendations", ["recommendation_type"], unique=False)
    op.create_index(op.f("ix_recommendations_run_id"), "recommendations", ["run_id"], unique=False)
    op.create_index(op.f("ix_recommendations_series_name"), "recommendations", ["series_name"], unique=False)
    op.create_index(op.f("ix_recommendations_source"), "recommendations", ["source"], unique=False)
    op.create_index(op.f("ix_recommendations_status"), "recommendations", ["status"], unique=False)
    op.create_index(op.f("ix_recommendations_user_id"), "recommendations", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_recommendations_user_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_status"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_source"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_series_name"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_run_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_recommendation_type"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_provider"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_model"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_local_series_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_local_book_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_generated_at"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_format_hint"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_created_at"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_confidence"), table_name="recommendations")
    op.drop_table("recommendations")

    op.drop_index(op.f("ix_recommendation_runs_user_id"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_status"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_started_at"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_source"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_recommendation_type"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_provider"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_model"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_generated_at"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_finished_at"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_error_code"), table_name="recommendation_runs")
    op.drop_index(op.f("ix_recommendation_runs_created_at"), table_name="recommendation_runs")
    op.drop_table("recommendation_runs")
