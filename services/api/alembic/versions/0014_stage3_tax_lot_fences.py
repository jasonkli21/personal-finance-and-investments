"""Add optimistic fencing for concurrent append-only lot adjustments.

Revision ID: 0014_stage3_tax_lot_fences
Revises: 0013_stage3_tax_lots
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_stage3_tax_lot_fences"
down_revision: str | None = "0013_stage3_tax_lots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tax_lots",
        sa.Column("state_revision", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("tax_lots", "state_revision")
