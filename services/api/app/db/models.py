"""Portable SQLAlchemy mappings for the core portfolio schema."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base metadata for Alembic and tests."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Issuer(TimestampMixin, Base):
    __tablename__ = "issuers"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    normalized_name: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)


class IssuerAlias(Base):
    __tablename__ = "issuer_aliases"
    __table_args__ = (
        UniqueConstraint(
            "issuer_id",
            "alias_namespace",
            "normalized_alias",
            name="uq_issuer_alias_scoped",
        ),
        Index("ix_issuer_aliases_normalized_alias", "normalized_alias"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    issuer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("issuers.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(200), nullable=False)
    alias_namespace: Mapped[str] = mapped_column(
        String(40), nullable=False, default="name", server_default="name"
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unreviewed", server_default="unreviewed"
    )


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    current_position_revision: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    current_position_snapshot_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "position_snapshots.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_accounts_current_position_snapshot",
        ),
    )
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="manual"
    )


class Security(TimestampMixin, Base):
    __tablename__ = "securities"
    __table_args__ = (
        CheckConstraint(
            "security_type IN ('equity', 'etf', 'cash', 'other')",
            name="ck_securities_security_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_type: Mapped[str] = mapped_column(String(20), nullable=False)
    display_ticker: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("issuers.id", ondelete="SET NULL")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class SecurityIdentifier(Base):
    """A source-backed identifier scoped by its namespace and venue."""

    __tablename__ = "security_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "namespace",
            "exchange",
            "normalized_value",
            "valid_from",
            name="uq_security_identifier_scoped_start",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_security_identifier_validity",
        ),
        Index("ix_security_identifiers_security", "security_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("securities.id", ondelete="CASCADE"),
        nullable=False,
    )
    namespace: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False)


class Quote(TimestampMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "as_of", "source", name="uq_quotes_security_asof_source"
        ),
        CheckConstraint("price >= 0", name="ck_quotes_price_nonnegative"),
        Index("ix_quotes_security_asof", "security_id", "as_of"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("securities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    quality_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="reported"
    )
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )


class PositionSnapshot(TimestampMixin, Base):
    __tablename__ = "position_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "source", "revision", name="uq_position_snapshot_revision"
        ),
        Index("ix_position_snapshots_account_asof", "account_id", "snapshot_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    valuation_source: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="accepted")
    revision: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PositionSnapshotLine(Base):
    __tablename__ = "position_snapshot_lines"
    __table_args__ = (
        CheckConstraint(
            "(security_id IS NOT NULL AND unresolved_ref IS NULL) OR "
            "(security_id IS NULL AND unresolved_ref IS NOT NULL)",
            name="ck_position_line_security_or_unresolved",
        ),
        Index("ix_position_lines_snapshot", "snapshot_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("position_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("securities.id", ondelete="RESTRICT")
    )
    unresolved_ref: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    reported_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    reported_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    original_row_ref: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    quality_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="reported"
    )


class PrivateFile(TimestampMixin, Base):
    """A private local file and its content identity; bytes stay outside SQL."""

    __tablename__ = "private_files"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_private_file_content_hash"),
        UniqueConstraint("storage_key", name="uq_private_file_storage_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(100), nullable=False)
    original_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)


class ImportAttempt(TimestampMixin, Base):
    """Reviewed position/fund source attempt with immutable source identity."""

    __tablename__ = "imports"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'positions' AND account_id IS NOT NULL AND "
            "fund_security_id IS NULL) OR "
            "(kind = 'fund' AND account_id IS NULL AND "
            "fund_security_id IS NOT NULL)",
            name="ck_import_scope",
        ),
        UniqueConstraint("idempotency_key", name="uq_import_idempotency_key"),
        Index("ix_imports_identity", "identity_hash", "interpretation_hash"),
        Index("ix_imports_file", "file_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("private_files.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    fund_security_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("securities.id", ondelete="RESTRICT")
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_label: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    interpretation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    review_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    expected_account_revision: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_of_import_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports.id", ondelete="SET NULL")
    )
    staging_snapshot_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("position_snapshots.id", ondelete="SET NULL"),
    )
    published_snapshot_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("position_snapshots.id", ondelete="SET NULL"),
    )
    diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )


class DocumentImport(TimestampMixin, Base):
    """Original statement and its deterministic position-import projection."""

    __tablename__ = "document_imports"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_document_import_idempotency"),
        UniqueConstraint(
            "file_id", "position_import_id", name="uq_document_import_link"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("private_files.id", ondelete="RESTRICT"),
        nullable=False,
    )
    position_import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("imports.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_label: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )


class ImportBatch(TimestampMixin, Base):
    """Idempotency marker for one bounded review or publication batch."""

    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint(
            "import_id",
            "purpose",
            "review_revision",
            "ordinal",
            name="uq_import_batch_identity",
        ),
        Index("ix_import_batches_import", "import_id", "purpose"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)


class ImportRow(Base):
    """Bounded raw evidence plus its explicitly reviewed interpretation."""

    __tablename__ = "import_rows"
    __table_args__ = (
        UniqueConstraint("import_id", "row_number", name="uq_import_row_number"),
        Index("ix_import_rows_import_status", "import_id", "row_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    raw_identifier: Mapped[str | None] = mapped_column(String(2000))
    raw_name: Mapped[str | None] = mapped_column(String(2000))
    raw_asset_type: Mapped[str | None] = mapped_column(String(2000))
    raw_quantity: Mapped[str | None] = mapped_column(String(2000))
    raw_price: Mapped[str | None] = mapped_column(String(2000))
    raw_currency: Mapped[str | None] = mapped_column(String(200))
    raw_weight_value: Mapped[str | None] = mapped_column(String(100))
    raw_weight_unit: Mapped[str | None] = mapped_column(String(24))
    security_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("securities.id", ondelete="RESTRICT")
    )
    normalized_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    normalized_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    normalized_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    currency: Mapped[str | None] = mapped_column(String(3))
    row_status: Mapped[str] = mapped_column(String(24), nullable=False)
    excluded: Mapped[bool] = mapped_column(nullable=False, default=False)
    correction_reason: Mapped[str | None] = mapped_column(Text)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ImportReviewEvent(Base):
    """Append-only audit event for a correction or explicit acknowledgement."""

    __tablename__ = "import_review_events"
    __table_args__ = (
        UniqueConstraint(
            "import_id", "review_revision", name="uq_import_review_revision"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    change_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class IssuerMappingEvent(Base):
    """Reviewed history for a security-to-issuer mapping change."""

    __tablename__ = "security_issuer_mapping_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("securities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_issuer_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("issuers.id", ondelete="SET NULL")
    )
    new_issuer_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("issuers.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class FundSnapshot(TimestampMixin, Base):
    """Immutable reviewed composition; staging records are never selected."""

    __tablename__ = "fund_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "import_id", "review_revision", name="uq_fund_import_revision"
        ),
        Index("ix_fund_snapshots_selection", "fund_security_id", "as_of", "status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    fund_security_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("securities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    import_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("imports.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reported_weight: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    recognized_weight: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FundLine(Base):
    __tablename__ = "fund_lines"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "row_number", name="uq_fund_line_row"),
        Index("ix_fund_lines_snapshot", "snapshot_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("fund_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    review_row_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_rows.id", ondelete="RESTRICT"),
        nullable=False,
    )
    security_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("securities.id", ondelete="RESTRICT")
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(24), nullable=False)
    raw_identifier: Mapped[str | None] = mapped_column(String(2000))
    raw_name: Mapped[str | None] = mapped_column(String(2000))
    match_status: Mapped[str] = mapped_column(String(24), nullable=False)


class Calculation(Base):
    """Private immutable report identity; snapshots remain financial truth."""

    __tablename__ = "portfolio_calculations"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    storage_key: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(80), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class TransactionImport(TimestampMixin, Base):
    """Reviewed bank/card CSV import attempt; source rows remain immutable."""

    __tablename__ = "transaction_imports"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_transaction_import_idempotency"),
        Index("ix_transaction_imports_account", "account_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("private_files.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_label: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    statement_start: Mapped[date | None] = mapped_column(Date)
    statement_end: Mapped[date | None] = mapped_column(Date)
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )


class SpendingCategory(TimestampMixin, Base):
    """User-defined stable spending category."""

    __tablename__ = "spending_categories"
    __table_args__ = (UniqueConstraint("slug", name="uq_spending_category_slug"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)


class FinancialTransaction(TimestampMixin, Base):
    """Canonical signed transaction or private, unpublished import observation."""

    __tablename__ = "financial_transactions"
    __table_args__ = (
        UniqueConstraint("import_id", "row_number", name="uq_transaction_import_row"),
        Index("ix_transactions_account_posted", "account_id", "posted_date"),
        Index("ix_transactions_import_status", "import_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    import_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transaction_imports.id", ondelete="RESTRICT")
    )
    row_number: Mapped[int | None] = mapped_column(Integer)
    source_label: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(200))
    raw_posted_date: Mapped[str | None] = mapped_column(String(100))
    posted_date: Mapped[date | None] = mapped_column(Date)
    raw_transaction_date: Mapped[str | None] = mapped_column(String(100))
    transaction_date: Mapped[date | None] = mapped_column(Date)
    raw_amount: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    raw_currency: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(3))
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_merchant: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_type: Mapped[str | None] = mapped_column(String(120))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    identity_resolution: Mapped[str | None] = mapped_column(String(24))
    duplicate_of_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("financial_transactions.id", ondelete="SET NULL")
    )
    classification: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unclassified"
    )
    category_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("spending_categories.id", ondelete="SET NULL")
    )
    category_source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unclassified"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MerchantCategoryRule(TimestampMixin, Base):
    """Versioned exact merchant-to-category rule; user changes are append-only."""

    __tablename__ = "merchant_category_rules"
    __table_args__ = (
        UniqueConstraint(
            "normalized_merchant", "version", name="uq_merchant_category_rule_version"
        ),
        Index("ix_merchant_category_rule_lookup", "normalized_merchant", "active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    normalized_merchant: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("spending_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class TransactionProviderIdentity(Base):
    """Unique selected native provider ID; staged rows never reserve identities."""

    __tablename__ = "transaction_provider_identities"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "source_label",
            "provider_transaction_id",
            name="uq_transaction_provider_identity",
        ),
        UniqueConstraint("transaction_id", name="uq_transaction_provider_transaction"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_label: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_transaction_id: Mapped[str] = mapped_column(String(200), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )


class TransactionReviewEvent(Base):
    """Append-only audit of import corrections and canonical edits."""

    __tablename__ = "transaction_review_events"
    __table_args__ = (
        Index("ix_transaction_events_transaction", "transaction_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    import_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("transaction_imports.id", ondelete="CASCADE")
    )
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    change_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TransactionSplit(Base):
    """Signed category allocations whose amounts must equal the parent."""

    __tablename__ = "transaction_splits"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id", "split_index", name="uq_transaction_split_index"
        ),
        Index("ix_transaction_splits_transaction", "transaction_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    split_index: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("spending_categories.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(500))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class TransferMatch(TimestampMixin, Base):
    """Explicit user-confirmed link between opposite-side account events."""

    __tablename__ = "transfer_matches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    first_transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    second_transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActiveTransferTransaction(Base):
    """Unique claim for each transaction in a currently confirmed transfer."""

    __tablename__ = "active_transfer_transactions"
    __table_args__ = (Index("ix_active_transfer_transactions_transfer", "transfer_id"),)

    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_transactions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    transfer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transfer_matches.id", ondelete="CASCADE"),
        nullable=False,
    )
