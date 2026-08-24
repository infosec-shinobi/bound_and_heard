"""add libby series snapshots

Revision ID: 20260818_0010
Revises: 20260817_0009
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_0010"
down_revision: str | None = "20260817_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "libby_series_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("libby_series_key", sa.String(length=100), nullable=True),
        sa.Column("libby_series_url", sa.String(length=1000), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("parsed_entry_count", sa.Integer(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_libby_series_snapshots_checksum"), "libby_series_snapshots", ["checksum"], unique=False)
    op.create_index(op.f("ix_libby_series_snapshots_created_at"), "libby_series_snapshots", ["created_at"], unique=False)
    op.create_index(op.f("ix_libby_series_snapshots_libby_series_key"), "libby_series_snapshots", ["libby_series_key"], unique=False)
    op.create_index(op.f("ix_libby_series_snapshots_parsed_entry_count"), "libby_series_snapshots", ["parsed_entry_count"], unique=False)
    op.create_index(op.f("ix_libby_series_snapshots_series_id"), "libby_series_snapshots", ["series_id"], unique=False)
    op.create_index(op.f("ix_libby_series_snapshots_user_id"), "libby_series_snapshots", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_libby_series_snapshots_user_id"), table_name="libby_series_snapshots")
    op.drop_index(op.f("ix_libby_series_snapshots_series_id"), table_name="libby_series_snapshots")
    op.drop_index(op.f("ix_libby_series_snapshots_parsed_entry_count"), table_name="libby_series_snapshots")
    op.drop_index(op.f("ix_libby_series_snapshots_libby_series_key"), table_name="libby_series_snapshots")
    op.drop_index(op.f("ix_libby_series_snapshots_created_at"), table_name="libby_series_snapshots")
    op.drop_index(op.f("ix_libby_series_snapshots_checksum"), table_name="libby_series_snapshots")
    op.drop_table("libby_series_snapshots")
