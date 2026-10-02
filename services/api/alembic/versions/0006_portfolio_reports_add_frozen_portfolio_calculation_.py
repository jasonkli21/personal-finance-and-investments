"""Add frozen portfolio calculation artifacts

Revision ID: 0006_portfolio_reports
Revises: 0005_fund_compositions
Create Date: 2026-10-02 10:02:48.659101
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_portfolio_reports"
down_revision: str | None = "0005_fund_compositions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_calculations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("calculation_version", sa.String(length=80), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_calculations")
