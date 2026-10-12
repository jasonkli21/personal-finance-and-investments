"""Add Finance-owned monthly discretionary budget records."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_monthly_discretionary_budgets"
down_revision: str | None = "0018_stage5_portfolio_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monthly_discretionary_budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "share_with_shopping",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount >= 0", name="ck_monthly_discretionary_budget_nonnegative"
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_monthly_discretionary_budget_revision"
        ),
        sa.CheckConstraint(
            "length(period) = 7 AND substr(period, 5, 1) = '-'",
            name="ck_monthly_discretionary_budget_period",
        ),
        sa.PrimaryKeyConstraint("id", name="monthly_discretionary_budgets_pkey"),
        sa.UniqueConstraint("period", name="uq_monthly_discretionary_budget_period"),
    )
    op.create_index(
        "ix_monthly_discretionary_budgets_period",
        "monthly_discretionary_budgets",
        ["period"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monthly_discretionary_budgets_period",
        table_name="monthly_discretionary_budgets",
    )
    op.drop_table("monthly_discretionary_budgets")
