"""add metadata enrichment models

Revision ID: 20260815_0007
Revises: 20260814_0006
Create Date: 2026-08-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260815_0007"
down_revision: str | None = "20260814_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("published_on", sa.Date(), nullable=True))
    op.add_column("books", sa.Column("publication_year", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_books_published_on"), "books", ["published_on"], unique=False)
    op.create_index(op.f("ix_books_publication_year"), "books", ["publication_year"], unique=False)

    op.create_table(
        "metadata_cache_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("lookup_type", sa.String(length=50), nullable=False),
        sa.Column("normalized_query", sa.String(length=1000), nullable=False),
        sa.Column("response_checksum", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "lookup_type",
            "normalized_query",
            "response_checksum",
            name="uq_metadata_cache_provider_lookup_query_checksum",
        ),
    )
    op.create_index(op.f("ix_metadata_cache_entries_fetched_at"), "metadata_cache_entries", ["fetched_at"], unique=False)
    op.create_index(op.f("ix_metadata_cache_entries_http_status"), "metadata_cache_entries", ["http_status"], unique=False)
    op.create_index(op.f("ix_metadata_cache_entries_lookup_type"), "metadata_cache_entries", ["lookup_type"], unique=False)
    op.create_index(op.f("ix_metadata_cache_entries_normalized_query"), "metadata_cache_entries", ["normalized_query"], unique=False)
    op.create_index(op.f("ix_metadata_cache_entries_provider"), "metadata_cache_entries", ["provider"], unique=False)
    op.create_index(op.f("ix_metadata_cache_entries_response_checksum"), "metadata_cache_entries", ["response_checksum"], unique=False)
    op.create_index(op.f("ix_metadata_cache_entries_status"), "metadata_cache_entries", ["status"], unique=False)

    op.create_table(
        "metadata_enrichment_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("lookup_type", sa.String(length=50), nullable=True),
        sa.Column("normalized_query", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("cache_entry_id", sa.Integer(), nullable=True),
        sa.Column("fields_applied", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["cache_entry_id"], ["metadata_cache_entries.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_metadata_enrichment_runs_book_id"), "metadata_enrichment_runs", ["book_id"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_cache_entry_id"), "metadata_enrichment_runs", ["cache_entry_id"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_created_at"), "metadata_enrichment_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_finished_at"), "metadata_enrichment_runs", ["finished_at"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_lookup_type"), "metadata_enrichment_runs", ["lookup_type"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_normalized_query"), "metadata_enrichment_runs", ["normalized_query"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_provider"), "metadata_enrichment_runs", ["provider"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_started_at"), "metadata_enrichment_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_status"), "metadata_enrichment_runs", ["status"], unique=False)
    op.create_index(op.f("ix_metadata_enrichment_runs_user_id"), "metadata_enrichment_runs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_metadata_enrichment_runs_user_id"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_status"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_started_at"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_provider"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_normalized_query"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_lookup_type"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_finished_at"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_created_at"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_cache_entry_id"), table_name="metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_enrichment_runs_book_id"), table_name="metadata_enrichment_runs")
    op.drop_table("metadata_enrichment_runs")
    op.drop_index(op.f("ix_metadata_cache_entries_status"), table_name="metadata_cache_entries")
    op.drop_index(op.f("ix_metadata_cache_entries_response_checksum"), table_name="metadata_cache_entries")
    op.drop_index(op.f("ix_metadata_cache_entries_provider"), table_name="metadata_cache_entries")
    op.drop_index(op.f("ix_metadata_cache_entries_normalized_query"), table_name="metadata_cache_entries")
    op.drop_index(op.f("ix_metadata_cache_entries_lookup_type"), table_name="metadata_cache_entries")
    op.drop_index(op.f("ix_metadata_cache_entries_http_status"), table_name="metadata_cache_entries")
    op.drop_index(op.f("ix_metadata_cache_entries_fetched_at"), table_name="metadata_cache_entries")
    op.drop_table("metadata_cache_entries")
    op.drop_index(op.f("ix_books_publication_year"), table_name="books")
    op.drop_index(op.f("ix_books_published_on"), table_name="books")
    op.drop_column("books", "publication_year")
    op.drop_column("books", "published_on")
