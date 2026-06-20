"""add book review state

Revision ID: 20260620_0003
Revises: 20260619_0002
Create Date: 2026-06-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260620_0003"
down_revision: str | None = "20260619_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("review_status", sa.String(length=50), nullable=True))
    op.add_column("books", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("books", sa.Column("review_note", sa.Text(), nullable=True))
    op.create_index(op.f("ix_books_review_status"), "books", ["review_status"], unique=False)
    op.create_index(op.f("ix_books_reviewed_at"), "books", ["reviewed_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_books_reviewed_at"), table_name="books")
    op.drop_index(op.f("ix_books_review_status"), table_name="books")
    op.drop_column("books", "review_note")
    op.drop_column("books", "reviewed_at")
    op.drop_column("books", "review_status")
