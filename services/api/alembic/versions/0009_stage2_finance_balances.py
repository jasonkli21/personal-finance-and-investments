"""Add source-labelled dated account balances.

Revision ID: 0009_stage2_finance_balances
Revises: 0008_stage2_transactions
Create Date: 2026-10-02 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_stage2_finance_balances"
down_revision: str | None = "0008_stage2_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_balance_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("balance_kind", sa.String(length=12), nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_account_balance_nonnegative"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="account_balance_observations_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="account_balance_observations_pkey"),
        sa.UniqueConstraint(
            "account_id", "as_of", "revision", name="uq_account_balance_revision"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_account_balance_idempotency"),
    )
    op.create_index(
        "ix_account_balances_account_date",
        "account_balance_observations",
        ["account_id", "as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_balances_account_date",
        table_name="account_balance_observations",
    )
    op.drop_table("account_balance_observations")
