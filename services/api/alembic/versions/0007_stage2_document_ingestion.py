"""Add original document and deterministic import linkage.

Revision ID: 0007_stage2_document_ingestion
Revises: 0006_portfolio_reports
Create Date: 2026-10-02 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_stage2_document_ingestion"
down_revision: str | None = "0006_portfolio_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("position_import_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["private_files.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["position_import_id"], ["imports.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="document_imports_pkey"),
        sa.UniqueConstraint(
            "file_id", "position_import_id", name="uq_document_import_link"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_document_import_idempotency"
        ),
    )


def downgrade() -> None:
    op.drop_table("document_imports")
