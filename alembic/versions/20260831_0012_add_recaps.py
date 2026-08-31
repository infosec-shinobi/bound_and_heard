"""add recaps

Revision ID: 20260831_0012
Revises: 20260818_0011
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_0012"
down_revision: str | None = "20260818_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recaps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("output_path", sa.String(length=1000), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "period_type", "year", "quarter", name="uq_recaps_user_period"),
    )
    op.create_index(op.f("ix_recaps_generated_at"), "recaps", ["generated_at"], unique=False)
    op.create_index(op.f("ix_recaps_period_type"), "recaps", ["period_type"], unique=False)
    op.create_index(op.f("ix_recaps_quarter"), "recaps", ["quarter"], unique=False)
    op.create_index(op.f("ix_recaps_user_id"), "recaps", ["user_id"], unique=False)
    op.create_index(op.f("ix_recaps_year"), "recaps", ["year"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_recaps_year"), table_name="recaps")
    op.drop_index(op.f("ix_recaps_user_id"), table_name="recaps")
    op.drop_index(op.f("ix_recaps_quarter"), table_name="recaps")
    op.drop_index(op.f("ix_recaps_period_type"), table_name="recaps")
    op.drop_index(op.f("ix_recaps_generated_at"), table_name="recaps")
    op.drop_table("recaps")
