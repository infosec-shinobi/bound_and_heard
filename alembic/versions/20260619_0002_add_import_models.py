"""add import models

Revision ID: 20260619_0002
Revises: dec226ca1253
Create Date: 2026-06-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260619_0002"
down_revision: str | None = "dec226ca1253"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("raw_file_path", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source", "checksum", name="uq_imports_user_source_checksum"),
    )
    op.create_index(op.f("ix_imports_checksum"), "imports", ["checksum"], unique=False)
    op.create_index(op.f("ix_imports_filename"), "imports", ["filename"], unique=False)
    op.create_index(op.f("ix_imports_imported_at"), "imports", ["imported_at"], unique=False)
    op.create_index(op.f("ix_imports_source"), "imports", ["source"], unique=False)
    op.create_index(op.f("ix_imports_status"), "imports", ["status"], unique=False)
    op.create_index(op.f("ix_imports_user_id"), "imports", ["user_id"], unique=False)

    op.create_table(
        "import_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_files_import_id"), "import_files", ["import_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_import_files_import_id"), table_name="import_files")
    op.drop_table("import_files")
    op.drop_index(op.f("ix_imports_user_id"), table_name="imports")
    op.drop_index(op.f("ix_imports_status"), table_name="imports")
    op.drop_index(op.f("ix_imports_source"), table_name="imports")
    op.drop_index(op.f("ix_imports_imported_at"), table_name="imports")
    op.drop_index(op.f("ix_imports_filename"), table_name="imports")
    op.drop_index(op.f("ix_imports_checksum"), table_name="imports")
    op.drop_table("imports")
