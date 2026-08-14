"""add series models

Revision ID: 20260814_0006
Revises: 20260813_0005
Create Date: 2026-08-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0006"
down_revision: str | None = "20260813_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("wants_to_continue", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_series_name"), "series", ["name"], unique=False)
    op.create_index(op.f("ix_series_status"), "series", ["status"], unique=False)
    op.create_index(op.f("ix_series_user_id"), "series", ["user_id"], unique=False)
    op.create_index(op.f("ix_series_wants_to_continue"), "series", ["wants_to_continue"], unique=False)

    op.create_table(
        "series_books",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("planned_title", sa.String(length=500), nullable=True),
        sa.Column("planned_author_name", sa.String(length=300), nullable=True),
        sa.Column("planned_format", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series_id", "book_id", name="uq_series_books_series_id_book_id"),
    )
    op.create_index(op.f("ix_series_books_book_id"), "series_books", ["book_id"], unique=False)
    op.create_index(op.f("ix_series_books_planned_author_name"), "series_books", ["planned_author_name"], unique=False)
    op.create_index(op.f("ix_series_books_planned_format"), "series_books", ["planned_format"], unique=False)
    op.create_index(op.f("ix_series_books_planned_title"), "series_books", ["planned_title"], unique=False)
    op.create_index(op.f("ix_series_books_position"), "series_books", ["position"], unique=False)
    op.create_index(op.f("ix_series_books_series_id"), "series_books", ["series_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_series_books_series_id"), table_name="series_books")
    op.drop_index(op.f("ix_series_books_position"), table_name="series_books")
    op.drop_index(op.f("ix_series_books_planned_title"), table_name="series_books")
    op.drop_index(op.f("ix_series_books_planned_format"), table_name="series_books")
    op.drop_index(op.f("ix_series_books_planned_author_name"), table_name="series_books")
    op.drop_index(op.f("ix_series_books_book_id"), table_name="series_books")
    op.drop_table("series_books")
    op.drop_index(op.f("ix_series_wants_to_continue"), table_name="series")
    op.drop_index(op.f("ix_series_user_id"), table_name="series")
    op.drop_index(op.f("ix_series_status"), table_name="series")
    op.drop_index(op.f("ix_series_name"), table_name="series")
    op.drop_table("series")
