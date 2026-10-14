"""Retain verified upstream authentication time without refreshing old sessions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_verified_session_auth_time"
down_revision: str | None = "0019_monthly_discretionary_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions", sa.Column("upstream_auth_time", sa.BigInteger(), nullable=True)
    )
    op.create_check_constraint(
        "ck_auth_session_upstream_time",
        "auth_sessions",
        "upstream_auth_time IS NULL OR upstream_auth_time >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_auth_session_upstream_time", "auth_sessions", type_="check")
    op.drop_column("auth_sessions", "upstream_auth_time")
