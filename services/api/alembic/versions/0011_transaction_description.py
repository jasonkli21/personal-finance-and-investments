"""Restore the corrected description column omitted from the local schema.

The independent DSQL 0008 plan already creates this column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_transaction_description"
down_revision: str | None = "0010_stage2_durable_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "financial_transactions", sa.Column("description", sa.Text(), nullable=True)
    )
    op.execute(
        sa.text("UPDATE financial_transactions SET description = raw_description")
    )
    op.alter_column("financial_transactions", "description", nullable=False)


def downgrade() -> None:
    op.drop_column("financial_transactions", "description")
