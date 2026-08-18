"""add genre models

Revision ID: 20260816_0008
Revises: 20260815_0007
Create Date: 2026-08-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260816_0008"
down_revision: str | None = "20260815_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "genres",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_genres_user_id_normalized_name"),
    )
    op.create_index(op.f("ix_genres_name"), "genres", ["name"], unique=False)
    op.create_index(op.f("ix_genres_normalized_name"), "genres", ["normalized_name"], unique=False)
    op.create_index(op.f("ix_genres_source"), "genres", ["source"], unique=False)
    op.create_index(op.f("ix_genres_user_id"), "genres", ["user_id"], unique=False)

    op.create_table(
        "book_genres",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("genre_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("raw_label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "genre_id", name="uq_book_genres_book_id_genre_id"),
    )
    op.create_index(op.f("ix_book_genres_book_id"), "book_genres", ["book_id"], unique=False)
    op.create_index(op.f("ix_book_genres_genre_id"), "book_genres", ["genre_id"], unique=False)
    op.create_index(op.f("ix_book_genres_source"), "book_genres", ["source"], unique=False)
    op.create_index(op.f("ix_book_genres_user_id"), "book_genres", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_book_genres_user_id"), table_name="book_genres")
    op.drop_index(op.f("ix_book_genres_source"), table_name="book_genres")
    op.drop_index(op.f("ix_book_genres_genre_id"), table_name="book_genres")
    op.drop_index(op.f("ix_book_genres_book_id"), table_name="book_genres")
    op.drop_table("book_genres")
    op.drop_index(op.f("ix_genres_user_id"), table_name="genres")
    op.drop_index(op.f("ix_genres_source"), table_name="genres")
    op.drop_index(op.f("ix_genres_normalized_name"), table_name="genres")
    op.drop_index(op.f("ix_genres_name"), table_name="genres")
    op.drop_table("genres")
