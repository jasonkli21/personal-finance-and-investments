"""Public API contracts for accounts, local security lookup and positions."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    account_type: str = Field(min_length=1, max_length=40)
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("name", "account_type")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class ErrorResponse(BaseModel):
    detail: str


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    account_type: str | None = Field(default=None, min_length=1, max_length=40)
    base_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    active: bool | None = None

    @field_validator("name", "account_type")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_a_change(self) -> "AccountPatch":
        if not self.model_fields_set:
            raise ValueError("At least one account field must be provided")
        return self


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    account_type: str
    base_currency: str
    active: bool
    source_type: str


class SecurityRead(BaseModel):
    id: UUID
    security_type: str
    display_ticker: str | None
    name: str
    currency: str


class SecurityResolution(BaseModel):
    status: Literal["resolved", "ambiguous", "unknown"]
    matches: list[SecurityRead]


class PositionInput(BaseModel):
    security_id: UUID
    quantity: str = Field(max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$")
    reported_price: str | None = Field(
        default=None, max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$"
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("quantity")
    @classmethod
    def quantity_precision(cls, value: str) -> str:
        if len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("Quantity exceeds NUMERIC(28, 10) precision")
        return value

    @field_validator("reported_price")
    @classmethod
    def price_precision(cls, value: str | None) -> str | None:
        if value is not None and len(value.split(".")[0]) > 14:
            raise ValueError("Price exceeds NUMERIC(24, 10) precision")
        return value


class PositionReplace(BaseModel):
    expected_revision: int | None = Field(ge=0)
    effective_date: date
    positions: list[PositionInput] = Field(max_length=500)


class PositionLineRead(BaseModel):
    id: UUID
    security: SecurityRead
    quantity: str
    reported_price: str | None
    reported_value: str | None
    currency: str
    price_as_of: date | None
    source: str
    quality_status: str


class PositionSnapshotRead(BaseModel):
    id: UUID
    account_id: UUID
    effective_date: date
    revision: int
    source: str
    positions: list[PositionLineRead]


class PositionsEnvelope(BaseModel):
    snapshot: PositionSnapshotRead | None
    current_revision: int


class OwnedValuationLine(BaseModel):
    position_id: UUID
    security_id: UUID
    ticker: str | None
    name: str
    quantity: str
    currency: str
    value: str | None
    value_currency: str | None
    price: str | None
    price_as_of: datetime | None
    price_source: str | None
    quality_status: str
    status: Literal["valued", "unpriced", "foreign_currency"]
    allocation_percent: str | None


class OwnedPortfolioRead(BaseModel):
    account_id: UUID
    snapshot_id: UUID | None
    effective_date: date | None
    as_of: date | None
    current_revision: int
    completeness: Literal["complete", "incomplete", "empty"]
    known_usd_subtotal: str
    total_usd: str | None
    percentages_available: bool
    lines: list[OwnedValuationLine]


class ImportCreated(BaseModel):
    id: UUID
    kind: Literal["positions", "fund"]
    status: str
    review_revision: int
    row_count: int
    batch_count: int
    duplicate: bool


class DocumentImportCreated(BaseModel):
    id: UUID
    file_id: UUID
    position_import_id: UUID
    status: str
    row_count: int
    duplicate: bool


class DocumentImportRead(BaseModel):
    id: UUID
    file_id: UUID
    position_import_id: UUID
    account_id: UUID
    effective_date: date
    source_label: str
    parser_version: str
    status: str
    row_count: int
    diagnostics: dict[str, Any]
    position_import_status: str
    filename: str


class AccountBalanceCreate(BaseModel):
    account_id: UUID
    as_of: date
    balance_kind: Literal["asset", "liability"]
    amount: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    source: str = Field(min_length=1, max_length=100)
    quality_status: Literal["reported", "estimated", "stale"] = "reported"
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("amount")
    @classmethod
    def balance_amount_precision(cls, value: str) -> str:
        if len(value.split(".")[0]) > 14:
            raise ValueError("Balance exceeds NUMERIC(24, 10) precision")
        return value

    @field_validator("source")
    @classmethod
    def trim_balance_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Balance source cannot be blank")
        return normalized


class AccountBalanceRead(BaseModel):
    id: UUID
    account_id: UUID
    as_of: date
    revision: int
    balance_kind: Literal["asset", "liability"]
    amount: str
    currency: str
    source: str
    quality_status: Literal["reported", "estimated", "stale"]


class FinanceCurrencyTotal(BaseModel):
    currency: str
    income: str
    net_spending: str
    net_cash_flow: str
    transaction_count: int


class FinanceCategoryTotal(BaseModel):
    category_id: UUID | None
    category_name: str
    currency: str
    net_spending: str


class NetWorthLine(BaseModel):
    account_id: UUID
    account_name: str
    account_type: str
    as_of: date | None
    currency: str | None
    amount: str | None
    source: str | None
    quality_status: str
    status: Literal["valued", "unavailable", "unpriced", "stale", "foreign_currency"]
    included: bool
    detail: str | None


class NetWorthCurrencyTotal(BaseModel):
    currency: str
    known_amount: str
    completeness: Literal["complete", "incomplete"]


class FinanceSummaryRead(BaseModel):
    month: date
    as_of: date
    transaction_policy: str
    currency_totals: list[FinanceCurrencyTotal]
    category_totals: list[FinanceCategoryTotal]
    net_worth: list[NetWorthCurrencyTotal]
    balances: list[NetWorthLine]
    coverage_gaps: list[str]
    exclusions: list[str]


class JobRead(BaseModel):
    id: UUID
    job_type: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    attempts: int
    max_attempts: int
    progress_stage: str
    progress_current: int
    progress_total: int | None
    cancel_requested: bool
    safe_error_code: str | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SpendingCategoryCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Category name cannot be blank")
        return normalized


class SpendingCategoryRead(BaseModel):
    id: UUID
    slug: str
    display_name: str


class TransactionImportCreated(BaseModel):
    id: UUID
    status: str
    row_count: int
    review_revision: int
    duplicate: bool


class TransactionRowRead(BaseModel):
    id: UUID
    row_number: int | None
    raw_payload: dict[str, Any]
    raw_posted_date: str | None
    posted_date: date | None
    raw_transaction_date: str | None
    transaction_date: date | None
    raw_amount: str | None
    amount: str | None
    raw_currency: str | None
    currency: str | None
    raw_description: str
    description: str
    raw_type: str | None
    provider_transaction_id: str | None
    status: str
    diagnostics: dict[str, Any]
    duplicate_candidates: list[UUID]


class TransactionImportReviewRead(BaseModel):
    id: UUID
    account_id: UUID
    source_label: str
    statement_start: date | None
    statement_end: date | None
    parser_version: str
    status: str
    review_revision: int
    row_count: int
    diagnostics: dict[str, Any]
    rows: list[TransactionRowRead]


class TransactionRowCorrection(BaseModel):
    expected_review_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    posted_date: date | None = None
    transaction_date: date | None = None
    amount: str | None = Field(
        default=None, max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$"
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    provider_transaction_id: str | None = Field(default=None, max_length=200)
    raw_type: str | None = Field(default=None, max_length=120)
    identity_resolution: Literal["keep", "duplicate", "update"] | None = None
    duplicate_of_transaction_id: UUID | None = None

    @field_validator("amount")
    @classmethod
    def transaction_amount_precision(cls, value: str | None) -> str | None:
        if value is not None and len(value.lstrip("-").split(".")[0]) > 14:
            raise ValueError("Amount exceeds NUMERIC(24, 10) precision")
        return value


class TransactionImportAction(BaseModel):
    expected_review_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class TransactionRead(BaseModel):
    id: UUID
    account_id: UUID
    posted_date: date
    transaction_date: date | None
    amount: str
    currency: str
    raw_description: str
    description: str
    raw_type: str | None
    provider_transaction_id: str | None
    source_label: str
    classification: str
    category_id: UUID | None
    category_slug: str | None
    category_name: str | None
    category_source: str
    revision: int
    split_count: int
    transfer_match_id: UUID | None


class TransactionManualCreate(BaseModel):
    account_id: UUID
    posted_date: date
    transaction_date: date | None = None
    amount: str = Field(max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    description: str = Field(min_length=1, max_length=2000)
    classification: Literal[
        "unclassified",
        "income",
        "expense",
        "refund",
        "transfer",
        "card_payment",
        "fee",
        "other",
    ] = "unclassified"
    category_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("amount")
    @classmethod
    def manual_amount_precision(cls, value: str) -> str:
        if len(value.lstrip("-").split(".")[0]) > 14:
            raise ValueError("Amount exceeds NUMERIC(24, 10) precision")
        return value


class TransactionPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    classification: (
        Literal[
            "unclassified",
            "income",
            "expense",
            "refund",
            "transfer",
            "card_payment",
            "fee",
            "other",
        ]
        | None
    ) = None
    category_id: UUID | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "TransactionPatch":
        if (
            "classification" not in self.model_fields_set
            and "category_id" not in self.model_fields_set
        ):
            raise ValueError("At least one transaction field must be provided")
        return self


class CategoryRuleCreate(BaseModel):
    merchant: str = Field(min_length=1, max_length=200)
    category_id: UUID
    priority: int = Field(default=100, ge=0, le=10000)


class CategoryRuleRead(BaseModel):
    id: UUID
    merchant: str
    normalized_merchant: str
    category_id: UUID
    priority: int
    version: int
    active: bool


class TransactionSplitInput(BaseModel):
    amount: str = Field(max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$")
    category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("amount")
    @classmethod
    def split_amount_precision(cls, value: str) -> str:
        if len(value.lstrip("-").split(".")[0]) > 14:
            raise ValueError("Split exceeds NUMERIC(24, 10) precision")
        return value


class TransactionSplitsReplace(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    splits: list[TransactionSplitInput] = Field(max_length=100)


class TransactionSplitRead(BaseModel):
    id: UUID
    split_index: int
    amount: str
    category_id: UUID | None
    category_slug: str | None
    category_name: str | None
    note: str | None


class TransferCreate(BaseModel):
    first_transaction_id: UUID
    second_transaction_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class TransferRead(BaseModel):
    id: UUID
    first_transaction_id: UUID
    second_transaction_id: UUID
    status: str
    match_method: str
    reason: str
    confirmed_at: datetime | None


class TransferCandidateRead(BaseModel):
    first_transaction: TransactionRead
    second_transaction: TransactionRead
    date_gap_days: int
    reason: str


class ImportRowRead(BaseModel):
    id: UUID
    row_number: int
    raw_payload: dict[str, str]
    raw_identifier: str | None
    raw_name: str | None
    raw_asset_type: str | None
    raw_weight_value: str | None = None
    raw_weight_unit: str | None = None
    normalized_weight: str | None = None
    raw_quantity: str | None
    raw_price: str | None
    raw_currency: str | None
    security_id: UUID | None
    security_label: str | None
    normalized_quantity: str | None
    normalized_price: str | None
    currency: str | None
    row_status: str
    excluded: bool
    correction_reason: str | None
    diagnostics: dict[str, str]


class ImportReviewRead(BaseModel):
    id: UUID
    kind: str
    account_id: UUID | None
    effective_date: date
    source_label: str
    status: str
    review_revision: int
    row_count: int
    expected_account_revision: int | None
    diagnostics: dict[str, str]
    rows: list[ImportRowRead]


class ImportRowCorrection(BaseModel):
    expected_review_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    security_id: UUID | None = None
    quantity: str | None = Field(default=None, max_length=40)
    price: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    excluded: bool | None = None

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A correction reason is required")
        return value

    @model_validator(mode="after")
    def require_a_correction(self) -> "ImportRowCorrection":
        if not any(
            value is not None
            for value in (
                self.security_id,
                self.quantity,
                self.price,
                self.currency,
                self.excluded,
            )
        ):
            raise ValueError("At least one row correction is required")
        return self


class ImportAction(BaseModel):
    expected_review_revision: int = Field(ge=1)
    reason: str = Field(default="Reviewed by user", min_length=1, max_length=500)


class IssuerCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("display_name")
    @classmethod
    def trim_issuer_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Issuer name cannot be blank")
        return value


class IssuerRead(BaseModel):
    id: UUID
    display_name: str


class SecurityCreate(BaseModel):
    security_type: Literal["equity", "etf", "cash", "other"]
    display_ticker: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    issuer_id: UUID | None = None
    identifier_namespace: str | None = Field(default=None, max_length=40)
    identifier_exchange: str = Field(default="", max_length=40)
    identifier_value: str | None = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def trim_security_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Security name cannot be blank")
        return value

    @model_validator(mode="after")
    def identifier_is_complete(self) -> "SecurityCreate":
        if bool(self.identifier_namespace) != bool(self.identifier_value):
            raise ValueError("Identifier namespace and value must be supplied together")
        return self


class IssuerAssignment(BaseModel):
    issuer_id: UUID | None
    expected_issuer_id: UUID | None
    reason: str = Field(min_length=1, max_length=500)


class QuoteCreate(BaseModel):
    security_id: UUID
    as_of: datetime
    price: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Quote timestamp must include a timezone")
        return value

    @field_validator("reason")
    @classmethod
    def trim_quote_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A quote source note is required")
        return value


class QuoteRead(BaseModel):
    id: UUID
    security_id: UUID
    as_of: datetime
    price: str
    currency: str
    source: str
    quality_status: str


class FundCorrection(BaseModel):
    expected_review_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    security_id: UUID | None = None
    weight: str | None = Field(default=None, max_length=30)
    asset_type: Literal["equity", "cash", "nested", "other", "unsupported"] | None = (
        None
    )


class FundSnapshotRead(BaseModel):
    id: UUID
    fund_security_id: UUID
    import_id: UUID
    as_of: date
    fetched_at: datetime
    source: str
    source_url: str | None
    parser_version: str
    content_hash: str
    quality_status: str
    reported_weight: str
    recognized_weight: str
    warnings: list[str]
    row_count: int


class ReportCreate(BaseModel):
    account_ids: list[UUID] = Field(default_factory=list, max_length=500)
    as_of: datetime | None = None
    include_archived: bool = False

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Use a timestamp with timezone")
        return value


class ReportSummary(BaseModel):
    id: UUID
    calculation_version: str
    input_hash: str
    generated_at: datetime
    valuation_at: datetime
    account_ids: list[UUID]
    reporting_currency: str
    included_valued_nav: str
    total_portfolio_nav: str | None
    nav_status: str
    percentages_available: bool
    security_coverage: str | None
    issuer_coverage: str | None
    attribution_numerator: str
    issuer_attribution_numerator: str
    issuer_unmapped_value: str
    coverage_denominator: str
    categories: dict[str, str]
    reconciled: bool
    warnings: list[str]


class ReportContribution(BaseModel):
    account_id: str
    account_name: str
    owned_label: str
    label: str
    category: str
    amount: str
    weight: str | None
    position_id: str
    position_snapshot_id: str
    position_as_of: str
    position_source: str
    position_quality: str
    security_id: str | None
    issuer_id: str | None
    quote_id: str | None
    quote_as_of: str | None
    quote_source: str | None
    quality_status: str
    fund_snapshot_id: str | None
    fund_as_of: str | None
    fund_fetched_at: str | None
    fund_source: str | None
    fund_source_url: str | None
    fund_quality: str | None
    fund_stale: bool


class ExposureRowRead(BaseModel):
    id: str
    label: str
    direct: str
    indirect: str
    total: str
    percentage: str | None
    included_valued_percentage: str | None


class OwnedReportLine(BaseModel):
    position_id: str
    account_id: str
    account_name: str
    position_snapshot_id: str
    position_revision: int
    position_as_of: str
    position_source: str
    position_quality: str
    security_id: str | None
    security_type: str
    label: str
    quantity: str
    price: str | None
    value: str | None
    currency: str
    status: str
    quote_id: str | None
    quote_as_of: str | None
    quote_source: str | None
    quality_status: str
    stale: bool


class ReportPage(BaseModel):
    calculation_id: UUID
    view: str
    total_rows: int
    offset: int
    limit: int
    rows: list[OwnedReportLine | ExposureRowRead]
