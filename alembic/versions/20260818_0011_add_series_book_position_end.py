"""add series book position end

Revision ID: 20260818_0011
Revises: 20260818_0010
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_0011"
down_revision: str | None = "20260818_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("series_books", sa.Column("position_end", sa.Float(), nullable=True))
    op.create_index(op.f("ix_series_books_position_end"), "series_books", ["position_end"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_series_books_position_end"), table_name="series_books")
    op.drop_column("series_books", "position_end")
