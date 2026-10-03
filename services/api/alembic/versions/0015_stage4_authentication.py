"""Add the explicitly bound personal principal and revocable web sessions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_stage4_authentication"
down_revision: str | None = "0014_stage3_tax_lot_fences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_principals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=1000), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="auth_principals_pkey"),
        sa.UniqueConstraint("scope_id", name="uq_auth_principals_scope"),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_auth_principals_issuer_subject"
        ),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["auth_principals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="auth_sessions_pkey"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index(
        "ix_auth_sessions_expiry", "auth_sessions", ["expires_at"]
    )
    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_subject", sa.String(length=200), nullable=True),
        sa.Column("scope_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=24), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="security_audit_events_pkey"),
    )
    op.create_index(
        "ix_security_audit_created", "security_audit_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_security_audit_created", table_name="security_audit_events")
    op.drop_table("security_audit_events")
    op.drop_index("ix_auth_sessions_expiry", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("auth_principals")
