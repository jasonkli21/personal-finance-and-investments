"""Add an explicit revision to replaceable position snapshots.

Revision ID: 0002_position_snapshot_revision
Revises: 0001_core_portfolio_schema
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_position_snapshot_revision"
down_revision: str | None = "0001_core_portfolio_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "current_position_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "position_snapshots",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("position_snapshots", "revision")
    op.drop_column("accounts", "current_position_revision")
