"""add libby series hints

Revision ID: 20260817_0009
Revises: 20260816_0008
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260817_0009"
down_revision: str | None = "20260816_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "libby_series_hints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("scrape_item_id", sa.Integer(), nullable=True),
        sa.Column("libby_series_key", sa.String(length=100), nullable=False),
        sa.Column("libby_series_url", sa.String(length=1000), nullable=False),
        sa.Column("raw_label", sa.String(length=500), nullable=False),
        sa.Column("series_name", sa.String(length=500), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["scrape_item_id"], ["scrape_job_items.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "libby_series_key", name="uq_libby_series_hints_book_id_series_key"),
    )
    op.create_index(op.f("ix_libby_series_hints_applied_at"), "libby_series_hints", ["applied_at"], unique=False)
    op.create_index(op.f("ix_libby_series_hints_book_id"), "libby_series_hints", ["book_id"], unique=False)
    op.create_index(op.f("ix_libby_series_hints_libby_series_key"), "libby_series_hints", ["libby_series_key"], unique=False)
    op.create_index(op.f("ix_libby_series_hints_position"), "libby_series_hints", ["position"], unique=False)
    op.create_index(op.f("ix_libby_series_hints_scrape_item_id"), "libby_series_hints", ["scrape_item_id"], unique=False)
    op.create_index(op.f("ix_libby_series_hints_series_name"), "libby_series_hints", ["series_name"], unique=False)
    op.create_index(op.f("ix_libby_series_hints_status"), "libby_series_hints", ["status"], unique=False)
    op.create_index(op.f("ix_libby_series_hints_user_id"), "libby_series_hints", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_libby_series_hints_user_id"), table_name="libby_series_hints")
    op.drop_index(op.f("ix_libby_series_hints_status"), table_name="libby_series_hints")
    op.drop_index(op.f("ix_libby_series_hints_series_name"), table_name="libby_series_hints")
    op.drop_index(op.f("ix_libby_series_hints_scrape_item_id"), table_name="libby_series_hints")
    op.drop_index(op.f("ix_libby_series_hints_position"), table_name="libby_series_hints")
    op.drop_index(op.f("ix_libby_series_hints_libby_series_key"), table_name="libby_series_hints")
    op.drop_index(op.f("ix_libby_series_hints_book_id"), table_name="libby_series_hints")
    op.drop_index(op.f("ix_libby_series_hints_applied_at"), table_name="libby_series_hints")
    op.drop_table("libby_series_hints")
