"""Add reviewed transaction imports, categorization, splits and transfers.

Revision ID: 0008_stage2_transactions
Revises: 0007_stage2_document_ingestion
Create Date: 2026-10-02 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_stage2_transactions"
down_revision: str | None = "0007_stage2_document_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spending_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="spending_categories_pkey"),
        sa.UniqueConstraint("slug", name="uq_spending_category_slug"),
    )
    op.create_table(
        "transaction_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("statement_start", sa.Date(), nullable=True),
        sa.Column("statement_end", sa.Date(), nullable=True),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="transaction_imports_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["private_files.id"],
            name="transaction_imports_file_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="transaction_imports_pkey"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_transaction_import_idempotency"
        ),
    )
    op.create_index(
        "ix_transaction_imports_account",
        "transaction_imports",
        ["account_id", "created_at"],
    )
    op.create_table(
        "financial_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=200), nullable=True),
        sa.Column("raw_posted_date", sa.String(length=100), nullable=True),
        sa.Column("posted_date", sa.Date(), nullable=True),
        sa.Column("raw_transaction_date", sa.String(length=100), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("raw_amount", sa.String(length=100), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("raw_currency", sa.String(length=40), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("raw_description", sa.Text(), nullable=False),
        sa.Column("normalized_merchant", sa.String(length=200), nullable=False),
        sa.Column("raw_type", sa.String(length=120), nullable=True),
        sa.Column(
            "raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("identity_resolution", sa.String(length=24), nullable=True),
        sa.Column("duplicate_of_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("category_source", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="financial_transactions_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["spending_categories.id"],
            name="financial_transactions_category_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_transaction_id"],
            ["financial_transactions.id"],
            name="financial_transactions_duplicate_of_transaction_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["transaction_imports.id"],
            name="financial_transactions_import_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="financial_transactions_pkey"),
        sa.UniqueConstraint(
            "idempotency_key", name="financial_transactions_idempotency_key_key"
        ),
        sa.UniqueConstraint(
            "import_id", "row_number", name="uq_transaction_import_row"
        ),
    )
    op.create_index(
        "ix_transactions_account_posted",
        "financial_transactions",
        ["account_id", "posted_date"],
    )
    op.create_index(
        "ix_transactions_import_status",
        "financial_transactions",
        ["import_id", "status"],
    )
    op.create_table(
        "transaction_provider_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=200), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="transaction_provider_identities_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transactions.id"],
            name="transaction_provider_identities_transaction_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="transaction_provider_identities_pkey"),
        sa.UniqueConstraint(
            "account_id",
            "source_label",
            "provider_transaction_id",
            name="uq_transaction_provider_identity",
        ),
        sa.UniqueConstraint(
            "transaction_id", name="uq_transaction_provider_transaction"
        ),
    )
    op.create_table(
        "merchant_category_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("normalized_merchant", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["spending_categories.id"],
            name="merchant_category_rules_category_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="merchant_category_rules_pkey"),
        sa.UniqueConstraint(
            "normalized_merchant", "version", name="uq_merchant_category_rule_version"
        ),
    )
    op.create_index(
        "ix_merchant_category_rule_lookup",
        "merchant_category_rules",
        ["normalized_merchant", "active"],
    )
    op.create_table(
        "transaction_review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=True),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "change_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["transaction_imports.id"],
            name="transaction_review_events_import_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transactions.id"],
            name="transaction_review_events_transaction_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="transaction_review_events_pkey"),
    )
    op.create_index(
        "ix_transaction_events_transaction",
        "transaction_review_events",
        ["transaction_id", "created_at"],
    )
    op.create_table(
        "transaction_splits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("split_index", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["spending_categories.id"],
            name="transaction_splits_category_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transactions.id"],
            name="transaction_splits_transaction_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="transaction_splits_pkey"),
        sa.UniqueConstraint(
            "transaction_id", "split_index", name="uq_transaction_split_index"
        ),
    )
    op.create_index(
        "ix_transaction_splits_transaction", "transaction_splits", ["transaction_id"]
    )
    op.create_table(
        "transfer_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("first_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("second_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_transaction_id"],
            ["financial_transactions.id"],
            name="transfer_matches_first_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["second_transaction_id"],
            ["financial_transactions.id"],
            name="transfer_matches_second_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="transfer_matches_pkey"),
    )
    op.create_table(
        "active_transfer_transactions",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transactions.id"],
            name="active_transfer_transactions_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["transfer_matches.id"],
            name="active_transfer_transactions_transfer_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "transaction_id", name="active_transfer_transactions_pkey"
        ),
    )
    op.create_index(
        "ix_active_transfer_transactions_transfer",
        "active_transfer_transactions",
        ["transfer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_active_transfer_transactions_transfer",
        table_name="active_transfer_transactions",
    )
    op.drop_table("active_transfer_transactions")
    op.drop_table("transfer_matches")
    op.drop_index("ix_transaction_splits_transaction", table_name="transaction_splits")
    op.drop_table("transaction_splits")
    op.drop_index(
        "ix_transaction_events_transaction", table_name="transaction_review_events"
    )
    op.drop_table("transaction_review_events")
    op.drop_index(
        "ix_merchant_category_rule_lookup", table_name="merchant_category_rules"
    )
    op.drop_table("merchant_category_rules")
    op.drop_index("ix_transactions_import_status", table_name="financial_transactions")
    op.drop_index("ix_transactions_account_posted", table_name="financial_transactions")
    op.drop_table("transaction_provider_identities")
    op.drop_table("financial_transactions")
    op.drop_index("ix_transaction_imports_account", table_name="transaction_imports")
    op.drop_table("transaction_imports")
    op.drop_table("spending_categories")
