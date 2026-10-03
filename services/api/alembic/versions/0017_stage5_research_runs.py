"""Add bounded, immutable offline research run/result snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_stage5_research_runs"
down_revision: str | None = "0016_stage5_research_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column(
            "selected_fact_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="research_runs_pkey"),
        sa.UniqueConstraint("idempotency_key", name="uq_research_run_idempotency"),
    )
    op.create_index(
        "ix_research_runs_issuer_created",
        "research_runs",
        ["issuer_id", "created_at"],
    )
    op.create_table(
        "research_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "result_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="research_results_pkey"),
        sa.UniqueConstraint("run_id", name="uq_research_result_run"),
    )


def downgrade() -> None:
    op.drop_table("research_results")
    op.drop_index("ix_research_runs_issuer_created", table_name="research_runs")
    op.drop_table("research_runs")
