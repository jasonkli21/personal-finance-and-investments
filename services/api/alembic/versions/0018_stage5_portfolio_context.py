"""Add immutable research notes, watchlist events and frozen context links."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_stage5_portfolio_context"
down_revision: str | None = "0017_stage5_research_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_thesis_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="research_thesis_notes_pkey"),
        sa.UniqueConstraint("issuer_id", "version", name="uq_research_thesis_version"),
        sa.UniqueConstraint(
            "issuer_id", "idempotency_key", name="uq_research_thesis_idempotency"
        ),
    )
    op.create_index(
        "ix_research_thesis_issuer_version",
        "research_thesis_notes",
        ["issuer_id", "version"],
    )
    op.create_table(
        "research_watchlist_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('added', 'removed')", name="ck_research_watchlist_action"
        ),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="research_watchlist_events_pkey"),
        sa.UniqueConstraint(
            "issuer_id", "version", name="uq_research_watchlist_event_version"
        ),
        sa.UniqueConstraint(
            "issuer_id",
            "idempotency_key",
            name="uq_research_watchlist_event_idempotency",
        ),
    )
    op.create_index(
        "ix_research_watchlist_issuer_version",
        "research_watchlist_events",
        ["issuer_id", "version"],
    )
    op.create_table(
        "research_run_contexts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_report_id", sa.Uuid(), nullable=True),
        sa.Column("thesis_note_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["portfolio_report_id"], ["portfolio_calculations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["thesis_note_id"], ["research_thesis_notes.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="research_run_contexts_pkey"),
        sa.UniqueConstraint("run_id", name="uq_research_run_context_run"),
    )


def downgrade() -> None:
    op.drop_table("research_run_contexts")
    op.drop_index(
        "ix_research_watchlist_issuer_version", table_name="research_watchlist_events"
    )
    op.drop_table("research_watchlist_events")
    op.drop_index(
        "ix_research_thesis_issuer_version", table_name="research_thesis_notes"
    )
    op.drop_table("research_thesis_notes")
