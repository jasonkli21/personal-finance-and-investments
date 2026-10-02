"""Retain published revisions and persist scoped security identifiers.

Revision ID: 0003_immutable_position_revisions_and_identifiers
Revises: 0002_position_snapshot_revision
Create Date: 2026-10-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0003_immutable_position_revisions_and_identifiers"
down_revision: str | None = "0002_position_snapshot_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _reconcile_manual_revisions(connection: sa.Connection) -> None:
    """Assign deterministic revisions and select the latest accepted snapshot.

    The prior implementation updated snapshots in place. This can only recover
    rows still present in that schema; it preserves every remaining row and line.
    When multiple rows are accepted, latest acceptance time wins, then revision,
    update time, creation time, and UUID provide stable tie breakers.
    """
    account_ids = connection.execute(
        sa.text("SELECT id FROM accounts ORDER BY id")
    ).scalars()
    read_snapshots = sa.text(
        "SELECT id, status, source FROM position_snapshots "
        "WHERE account_id = :account_id ORDER BY source, created_at, id"
    )
    read_selected = sa.text(
        "SELECT id FROM position_snapshots "
        "WHERE account_id = :account_id AND source = 'manual' "
        "AND status = 'accepted' "
        "ORDER BY accepted_at DESC NULLS LAST, revision DESC, updated_at DESC, "
        "created_at DESC, id DESC LIMIT 1"
    )
    update_revisions = sa.text(
        "UPDATE position_snapshots SET revision = :revision, status = :status "
        "WHERE id = :id"
    )
    update_account = sa.text(
        "UPDATE accounts SET current_position_revision = :current_revision, "
        "current_position_snapshot_id = :snapshot_id WHERE id = :account_id"
    )

    for account_id in account_ids:
        rows = list(connection.execute(read_snapshots, {"account_id": account_id}))
        selected_id = connection.execute(
            read_selected, {"account_id": account_id}
        ).scalar_one_or_none()
        updates: list[dict[str, Any]] = []
        next_revision_by_source: dict[str, int] = {}
        manual_rows = [row for row in rows if row.source == "manual"]
        ordered_manual = [row for row in manual_rows if row.id != selected_id]
        if selected_id is not None:
            ordered_manual.append(
                next(row for row in manual_rows if row.id == selected_id)
            )
        ordered_by_source = {
            "manual": ordered_manual,
            **{
                source: [row for row in rows if row.source == source]
                for source in {row.source for row in rows if row.source != "manual"}
            },
        }
        for source, source_rows in ordered_by_source.items():
            for index, row in enumerate(source_rows, start=1):
                next_revision_by_source[source] = index
                updates.append(
                    {
                        "id": row.id,
                        "revision": index,
                        "status": (
                            "accepted"
                            if row.id == selected_id
                            else "superseded"
                            if source == "manual" and row.status == "accepted"
                            else row.status
                        ),
                    }
                )
        for start in range(0, len(updates), 200):
            connection.execute(update_revisions, updates[start : start + 200])
        connection.execute(
            update_account,
            {
                "account_id": account_id,
                "current_revision": next_revision_by_source.get("manual", 0),
                "snapshot_id": selected_id,
            },
        )


def upgrade() -> None:
    op.add_column(
        "accounts", sa.Column("current_position_snapshot_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "issuer_aliases",
        sa.Column(
            "alias_namespace",
            sa.String(length=40),
            server_default="name",
            nullable=False,
        ),
    )
    op.add_column(
        "issuer_aliases",
        sa.Column(
            "review_status",
            sa.String(length=24),
            server_default="unreviewed",
            nullable=False,
        ),
    )
    op.create_table(
        "security_identifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=40), nullable=False),
        sa.Column("exchange", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("normalized_value", sa.String(length=128), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_security_identifier_validity",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["securities.id"],
            name="fk_security_identifiers_security",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "namespace",
            "exchange",
            "normalized_value",
            "valid_from",
            name="uq_security_identifier_scoped_start",
        ),
    )

    op.drop_constraint(
        "uq_position_snapshot_identity", "position_snapshots", type_="unique"
    )
    op.drop_constraint("uq_issuer_alias", "issuer_aliases", type_="unique")
    _reconcile_manual_revisions(op.get_bind())
    op.create_unique_constraint(
        "uq_position_snapshot_revision",
        "position_snapshots",
        ["account_id", "source", "revision"],
    )
    op.create_unique_constraint(
        "uq_issuer_alias_scoped",
        "issuer_aliases",
        ["issuer_id", "alias_namespace", "normalized_alias"],
    )
    op.create_index(
        "ix_security_identifiers_security", "security_identifiers", ["security_id"]
    )
    op.create_foreign_key(
        "fk_accounts_current_position_snapshot",
        "accounts",
        "position_snapshots",
        ["current_position_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Revision 0003 is intentionally not reversible: removing immutable "
        "position history or identifier provenance would discard accepted data."
    )
