"""add progress enjoyed and read count

Revision ID: 20260813_0005
Revises: 20260811_0004
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260813_0005"
down_revision: str | None = "20260811_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("book_progress", sa.Column("enjoyed_seconds", sa.Integer(), nullable=True))
    op.add_column("book_progress", sa.Column("read_count", sa.Integer(), nullable=True))
    op.execute("UPDATE book_progress SET enjoyed_seconds = position_seconds WHERE enjoyed_seconds IS NULL")


def downgrade() -> None:
    op.drop_column("book_progress", "read_count")
    op.drop_column("book_progress", "enjoyed_seconds")
