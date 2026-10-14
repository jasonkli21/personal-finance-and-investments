"""Immutable delegated source command metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0021_delegated_source_commands"
down_revision = "0020_verified_session_auth_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delegated_source_commands",
        sa.Column("command_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "principal_id",
            sa.Uuid(),
            sa.ForeignKey("auth_principals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT 1 FROM delegated_source_commands LIMIT 1")):
        raise RuntimeError("Cannot discard retained delegated task recovery state")
    op.drop_table("delegated_source_commands")
