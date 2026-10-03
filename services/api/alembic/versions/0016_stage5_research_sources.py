"""Add dated, user-registered research documents and reported facts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_stage5_research_sources"
down_revision: str | None = "0015_stage4_authentication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer_id", sa.Uuid(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("accession_number", sa.String(length=20), nullable=False),
        sa.Column("form_type", sa.String(length=12), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="research_documents_pkey"),
        sa.UniqueConstraint(
            "issuer_id", "accession_number", name="uq_research_document_accession"
        ),
    )
    op.create_index(
        "ix_research_documents_issuer_filed",
        "research_documents",
        ["issuer_id", "filing_date"],
    )
    op.create_table(
        "reported_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy", sa.String(length=40), nullable=False),
        sa.Column("concept", sa.String(length=100), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column(
            "normalized_value", sa.Numeric(precision=28, scale=10), nullable=True
        ),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("period_kind", sa.String(length=12), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("instant", sa.Date(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(length=3), nullable=True),
        sa.Column("context_ref", sa.String(length=100), nullable=True),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["research_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="reported_facts_pkey"),
        sa.UniqueConstraint("idempotency_key", name="uq_reported_fact_idempotency"),
    )
    op.create_index(
        "ix_reported_facts_document_concept",
        "reported_facts",
        ["document_id", "taxonomy", "concept"],
    )


def downgrade() -> None:
    op.drop_index("ix_reported_facts_document_concept", table_name="reported_facts")
    op.drop_table("reported_facts")
    op.drop_index("ix_research_documents_issuer_filed", table_name="research_documents")
    op.drop_table("research_documents")
