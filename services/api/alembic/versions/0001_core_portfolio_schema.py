"""Create the portable core portfolio schema.

Revision ID: 0001_core_portfolio_schema
Revises:
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_core_portfolio_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "issuers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("account_type", sa.String(length=40), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "issuer_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("normalized_alias", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer_id", "normalized_alias", name="uq_issuer_alias"),
    )
    op.create_index(
        "ix_issuer_aliases_normalized_alias", "issuer_aliases", ["normalized_alias"]
    )
    op.create_table(
        "securities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("security_type", sa.String(length=20), nullable=False),
        sa.Column("display_ticker", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("issuer_id", sa.Uuid(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "security_type IN ('equity', 'etf', 'cash', 'other')",
            name="ck_securities_security_type",
        ),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "position_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("valuation_source", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "snapshot_at", "source", name="uq_position_snapshot_identity"
        ),
    )
    op.create_index(
        "ix_position_snapshots_account_asof",
        "position_snapshots",
        ["account_id", "snapshot_at"],
    )
    op.create_table(
        "quotes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column(
            "provider_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_quotes_price_nonnegative"),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "security_id", "as_of", "source", name="uq_quotes_security_asof_source"
        ),
    )
    op.create_index("ix_quotes_security_asof", "quotes", ["security_id", "as_of"])
    op.create_table(
        "position_snapshot_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=True),
        sa.Column("unresolved_ref", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("reported_value", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("reported_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("original_row_ref", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "(security_id IS NOT NULL AND unresolved_ref IS NULL) OR "
            "(security_id IS NULL AND unresolved_ref IS NOT NULL)",
            name="ck_position_line_security_or_unresolved",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["position_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_position_lines_snapshot", "position_snapshot_lines", ["snapshot_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_position_lines_snapshot", table_name="position_snapshot_lines")
    op.drop_table("position_snapshot_lines")
    op.drop_index("ix_quotes_security_asof", table_name="quotes")
    op.drop_table("quotes")
    op.drop_index("ix_position_snapshots_account_asof", table_name="position_snapshots")
    op.drop_table("position_snapshots")
    op.drop_table("securities")
    op.drop_index("ix_issuer_aliases_normalized_alias", table_name="issuer_aliases")
    op.drop_table("issuer_aliases")
    op.drop_table("accounts")
    op.drop_table("issuers")
