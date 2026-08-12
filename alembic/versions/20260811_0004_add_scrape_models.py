"""add scrape models

Revision ID: 20260811_0004
Revises: 20260620_0003
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260811_0004"
down_revision: str | None = "20260620_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrape_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scrape_jobs_created_at"), "scrape_jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_scrape_jobs_finished_at"), "scrape_jobs", ["finished_at"], unique=False)
    op.create_index(op.f("ix_scrape_jobs_source"), "scrape_jobs", ["source"], unique=False)
    op.create_index(op.f("ix_scrape_jobs_started_at"), "scrape_jobs", ["started_at"], unique=False)
    op.create_index(op.f("ix_scrape_jobs_status"), "scrape_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_scrape_jobs_user_id"), "scrape_jobs", ["user_id"], unique=False)

    op.create_table(
        "scrape_job_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("latest_borrowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scraped_borrowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["scrape_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scrape_job_items_book_id"), "scrape_job_items", ["book_id"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_error_code"), "scrape_job_items", ["error_code"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_finished_at"), "scrape_job_items", ["finished_at"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_job_id"), "scrape_job_items", ["job_id"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_last_attempted_at"), "scrape_job_items", ["last_attempted_at"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_last_scraped_borrowed_at"), "scrape_job_items", ["last_scraped_borrowed_at"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_latest_borrowed_at"), "scrape_job_items", ["latest_borrowed_at"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_queued_at"), "scrape_job_items", ["queued_at"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_started_at"), "scrape_job_items", ["started_at"], unique=False)
    op.create_index(op.f("ix_scrape_job_items_status"), "scrape_job_items", ["status"], unique=False)

    op.create_table(
        "scrape_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_type", sa.String(length=50), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("progress_percent", sa.Float(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["scrape_job_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scrape_snapshots_checksum"), "scrape_snapshots", ["checksum"], unique=False)
    op.create_index(op.f("ix_scrape_snapshots_created_at"), "scrape_snapshots", ["created_at"], unique=False)
    op.create_index(op.f("ix_scrape_snapshots_item_id"), "scrape_snapshots", ["item_id"], unique=False)
    op.create_index(op.f("ix_scrape_snapshots_snapshot_type"), "scrape_snapshots", ["snapshot_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scrape_snapshots_snapshot_type"), table_name="scrape_snapshots")
    op.drop_index(op.f("ix_scrape_snapshots_item_id"), table_name="scrape_snapshots")
    op.drop_index(op.f("ix_scrape_snapshots_created_at"), table_name="scrape_snapshots")
    op.drop_index(op.f("ix_scrape_snapshots_checksum"), table_name="scrape_snapshots")
    op.drop_table("scrape_snapshots")
    op.drop_index(op.f("ix_scrape_job_items_status"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_started_at"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_queued_at"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_latest_borrowed_at"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_last_scraped_borrowed_at"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_last_attempted_at"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_job_id"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_finished_at"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_error_code"), table_name="scrape_job_items")
    op.drop_index(op.f("ix_scrape_job_items_book_id"), table_name="scrape_job_items")
    op.drop_table("scrape_job_items")
    op.drop_index(op.f("ix_scrape_jobs_user_id"), table_name="scrape_jobs")
    op.drop_index(op.f("ix_scrape_jobs_status"), table_name="scrape_jobs")
    op.drop_index(op.f("ix_scrape_jobs_started_at"), table_name="scrape_jobs")
    op.drop_index(op.f("ix_scrape_jobs_source"), table_name="scrape_jobs")
    op.drop_index(op.f("ix_scrape_jobs_finished_at"), table_name="scrape_jobs")
    op.drop_index(op.f("ix_scrape_jobs_created_at"), table_name="scrape_jobs")
    op.drop_table("scrape_jobs")
