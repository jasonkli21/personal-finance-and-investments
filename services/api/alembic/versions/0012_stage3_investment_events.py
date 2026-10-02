"""Store explicit historical investment events with provenance.

Revision ID: 0012_stage3_investment_events
Revises: 0011_transaction_description
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_stage3_investment_events"
down_revision: str | None = "0011_transaction_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("cash_amount", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("is_external_flow", sa.Boolean(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=False),
        sa.Column("source_event_id", sa.String(length=200), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "raw_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('buy', 'sell', 'dividend', 'fee', 'deposit', "
            "'withdrawal', 'transfer_in', 'transfer_out', 'split', 'adjustment', "
            "'other')",
            name="ck_investment_event_type",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="investment_events_pkey"),
        sa.UniqueConstraint("idempotency_key", name="uq_investment_event_idempotency"),
    )
    op.create_index(
        "ix_investment_events_account_date",
        "investment_events",
        ["account_id", "effective_date"],
    )
    op.create_index(
        "ix_investment_events_security_date",
        "investment_events",
        ["security_id", "effective_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_investment_events_security_date", table_name="investment_events")
    op.drop_index("ix_investment_events_account_date", table_name="investment_events")
    op.drop_table("investment_events")
