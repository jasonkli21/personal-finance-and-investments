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
