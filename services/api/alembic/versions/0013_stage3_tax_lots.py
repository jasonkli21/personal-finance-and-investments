"""Add reviewed supplied lots and immutable lot adjustments.

Revision ID: 0013_stage3_tax_lots
Revises: 0012_stage3_investment_events
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_stage3_tax_lots"
down_revision: str | None = "0012_stage3_investment_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tax_lot_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["file_id"], ["private_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="tax_lot_imports_pkey"),
        sa.UniqueConstraint("idempotency_key", name="uq_tax_lot_import_idempotency"),
        sa.UniqueConstraint(
            "account_id", "source_label", "file_sha256", name="uq_tax_lot_import_file"
        ),
    )
    op.create_index(
        "ix_tax_lot_imports_account_created",
        "tax_lot_imports",
        ["account_id", "created_at"],
    )
    op.create_table(
        "tax_lot_import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column(
            "raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("raw_ticker", sa.String(length=200), nullable=True),
        sa.Column("raw_source_lot_id", sa.String(length=200), nullable=True),
        sa.Column("security_id", sa.Uuid(), nullable=True),
        sa.Column("acquired_at", sa.Date(), nullable=True),
        sa.Column(
            "initial_quantity", sa.Numeric(precision=28, scale=10), nullable=True
        ),
        sa.Column(
            "remaining_quantity", sa.Numeric(precision=28, scale=10), nullable=True
        ),
        sa.Column("initial_basis", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("remaining_basis", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("basis_currency", sa.String(length=3), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("row_status", sa.String(length=24), nullable=False),
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"], ["tax_lot_imports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="tax_lot_import_rows_pkey"),
        sa.UniqueConstraint("import_id", "row_number", name="uq_tax_lot_import_row"),
    )
    op.create_index(
        "ix_tax_lot_import_rows_import",
        "tax_lot_import_rows",
        ["import_id", "row_number"],
    )
    op.create_table(
        "tax_lots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("import_row_id", sa.Uuid(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("source_lot_id", sa.String(length=200), nullable=True),
        sa.Column("identity_key", sa.String(length=64), nullable=False),
        sa.Column("acquired_at", sa.Date(), nullable=True),
        sa.Column(
            "initial_quantity", sa.Numeric(precision=28, scale=10), nullable=True
        ),
        sa.Column(
            "remaining_quantity", sa.Numeric(precision=28, scale=10), nullable=False
        ),
        sa.Column("initial_basis", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("remaining_basis", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("basis_currency", sa.String(length=3), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["tax_lot_imports.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["import_row_id"], ["tax_lot_import_rows.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="tax_lots_pkey"),
        sa.UniqueConstraint(
            "account_id", "source_label", "identity_key", name="uq_tax_lot_identity"
        ),
        sa.UniqueConstraint("import_row_id", name="uq_tax_lots_import_row"),
    )
    op.create_index(
        "ix_tax_lots_account_security", "tax_lots", ["account_id", "security_id"]
    )
    op.create_index(
        "ix_tax_lots_security_acquired", "tax_lots", ["security_id", "acquired_at"]
    )
    op.create_table(
        "tax_lot_adjustments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tax_lot_id", sa.Uuid(), nullable=False),
        sa.Column("adjustment_type", sa.String(length=32), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("basis_delta", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("basis_currency", sa.String(length=3), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "raw_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tax_lot_id"], ["tax_lots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="tax_lot_adjustments_pkey"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_tax_lot_adjustment_idempotency"
        ),
    )
    op.create_index(
        "ix_tax_lot_adjustments_lot_date",
        "tax_lot_adjustments",
        ["tax_lot_id", "effective_date"],
    )
    op.create_table(
        "tax_lot_review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("import_row_id", sa.Uuid(), nullable=True),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "change_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"], ["tax_lot_imports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_row_id"], ["tax_lot_import_rows.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="tax_lot_review_events_pkey"),
    )
    op.create_index(
        "ix_tax_lot_review_events_import",
        "tax_lot_review_events",
        ["import_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tax_lot_review_events_import", table_name="tax_lot_review_events")
    op.drop_table("tax_lot_review_events")
    op.drop_index("ix_tax_lot_adjustments_lot_date", table_name="tax_lot_adjustments")
    op.drop_table("tax_lot_adjustments")
    op.drop_index("ix_tax_lots_security_acquired", table_name="tax_lots")
    op.drop_index("ix_tax_lots_account_security", table_name="tax_lots")
    op.drop_table("tax_lots")
    op.drop_index("ix_tax_lot_import_rows_import", table_name="tax_lot_import_rows")
    op.drop_table("tax_lot_import_rows")
    op.drop_index("ix_tax_lot_imports_account_created", table_name="tax_lot_imports")
    op.drop_table("tax_lot_imports")
