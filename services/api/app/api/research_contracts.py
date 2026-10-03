"""Finance-owned, versioned contracts for offline public-research records."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.contracts import IssuerRead


class ResearchDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer_id: UUID
    cik: str = Field(min_length=1, max_length=10)
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    form_type: str = Field(min_length=1, max_length=12, pattern=r"^[A-Z0-9/-]+$")
    title: str = Field(min_length=1, max_length=300)
    source_url: str = Field(min_length=1, max_length=2048)
    filing_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None

    @field_validator("cik")
    @classmethod
    def normalize_cik(cls, value: str) -> str:
        value = value.strip()
        if not value.isdecimal() or len(value) > 10:
            raise ValueError("CIK must contain at most 10 digits")
        return value.zfill(10)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Title cannot be blank")
        return value

    @field_validator("source_url")
    @classmethod
    def sec_public_url_only(cls, value: str) -> str:
        value = value.strip()
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.hostname not in {"sec.gov", "www.sec.gov", "data.sec.gov"}
            or parts.username is not None
            or parts.password is not None
            or parts.port is not None
            or parts.query
            or parts.fragment
            or not parts.path.startswith("/")
        ):
            raise ValueError("Source URL must be a public SEC HTTPS URL")
        return urlunsplit(("https", parts.netloc.lower(), parts.path, "", ""))

    @field_validator("filing_date", "period_start", "period_end")
    @classmethod
    def source_dates_not_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Filing and reporting dates cannot be in the future")
        return value

    @model_validator(mode="after")
    def ordered_period(self) -> "ResearchDocumentCreate":
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("Document period requires both start and end dates")
        if (
            self.period_start
            and self.period_end
            and self.period_end < self.period_start
        ):
            raise ValueError("Document period end precedes its start")
        return self


class ResearchDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    issuer_id: UUID
    cik: str
    accession_number: str
    form_type: str
    title: str
    source_url: str
    filing_date: date | None
    period_start: date | None
    period_end: date | None
    recorded_at: datetime
    source_status: Literal["user_supplied_unverified"]


class ReportedFactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    taxonomy: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    concept: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    raw_value: str = Field(min_length=1, max_length=1000)
    normalized_value: str | None = Field(
        default=None, max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$"
    )
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    period_kind: Literal["duration", "instant"]
    period_start: date | None = None
    period_end: date | None = None
    instant: date | None = None
    fiscal_year: int | None = Field(default=None, ge=1900, le=2200)
    fiscal_period: Literal["Q1", "Q2", "Q3", "Q4", "H1", "H2", "FY"] | None = None
    context_ref: str | None = Field(default=None, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("normalized_value")
    @classmethod
    def financial_precision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Normalized value must be a decimal string") from exc
        if not parsed.is_finite() or len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("Normalized value exceeds NUMERIC(28, 10) precision")
        return value

    @field_validator("raw_value", "unit", "idempotency_key")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("period_start", "period_end", "instant")
    @classmethod
    def period_dates_not_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Reporting dates cannot be in the future")
        return value

    @model_validator(mode="after")
    def period_shape(self) -> "ReportedFactCreate":
        if self.period_kind == "duration":
            if (
                self.instant is not None
                or self.period_start is None
                or self.period_end is None
            ):
                raise ValueError("Duration facts require start/end and no instant")
            if self.period_end < self.period_start:
                raise ValueError("Period end precedes its start")
        elif (
            self.instant is None
            or self.period_start is not None
            or self.period_end is not None
        ):
            raise ValueError("Instant facts require only an instant date")
        if (self.fiscal_year is None) != (self.fiscal_period is None):
            raise ValueError("Fiscal year and period must be supplied together")
        return self


class ReportedFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    taxonomy: str
    concept: str
    raw_value: str
    normalized_value: str | None
    unit: str
    currency: str | None
    period_kind: Literal["duration", "instant"]
    period_start: date | None
    period_end: date | None
    instant: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    context_ref: str | None
    quality_status: Literal["user_supplied_unverified"]
    idempotency_key: str
    created_at: datetime

    @field_validator("normalized_value", mode="before")
    @classmethod
    def decimal_to_string(cls, value: Any) -> Any:
        if value is None:
            return None
        parsed = Decimal(str(value))
        return format(parsed.normalize(), "f") if parsed else "0"


class ResearchFactObservation(BaseModel):
    fact: ReportedFactRead
    document: ResearchDocumentRead


class ResearchCompanyRead(BaseModel):
    issuer: IssuerRead
    documents: list[ResearchDocumentRead]
    facts: list[ResearchFactObservation]


class FactComparisonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prior_fact_id: UUID
    current_fact_id: UUID


class FactComparisonRead(BaseModel):
    status: Literal["comparable", "unavailable"]
    methodology_version: Literal["same-fiscal-period-yoy-v1"]
    prior: ResearchFactObservation
    current: ResearchFactObservation
    absolute_change: str | None
    percent_change: str | None
    diagnostics: list[str]


class ResearchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer_id: UUID
    question: str = Field(min_length=1, max_length=500)
    fact_ids: list[UUID] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=1, max_length=128)
    portfolio_report_id: UUID | None = None
    thesis_note_id: UUID | None = None

    @field_validator("question", "idempotency_key")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("fact_ids")
    @classmethod
    def unique_fact_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Fact selection contains duplicates")
        return value


class ResearchCitationRead(BaseModel):
    fact_id: UUID
    document_id: UUID
    accession_number: str
    form_type: str
    source_url: str
    title: str
    filing_date: date | None
    quality_status: Literal["user_supplied_unverified"]


class ResearchPortfolioContribution(BaseModel):
    account_id: UUID
    account_name: str
    exposure_kind: Literal["direct", "indirect"]
    amount: str
    security_id: UUID
    position_id: UUID
    position_snapshot_id: UUID
    position_as_of: date
    position_source: str
    position_quality: str
    quote_id: UUID | None
    quote_as_of: datetime | None
    quote_source: str | None
    quality_status: str
    fund_snapshot_id: UUID | None
    fund_as_of: date | None
    fund_fetched_at: datetime | None
    fund_source: str | None
    fund_source_url: str | None
    fund_quality: str | None
    fund_stale: bool


class ResearchPortfolioContext(BaseModel):
    status: Literal["matched", "issuer_unmapped"]
    report_id: UUID
    report_input_hash: str
    report_generated_at: datetime
    valuation_at: datetime
    account_ids: list[UUID]
    nav_status: Literal["complete", "incomplete"]
    issuer_id: UUID
    issuer_name: str
    direct_exposure: str | None
    indirect_exposure: str | None
    total_exposure: str | None
    reconciled: bool
    contributions: list[ResearchPortfolioContribution]
    warnings: list[str]


class ResearchThesisNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer_id: UUID
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("text", "idempotency_key")
    @classmethod
    def clean_note_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class ResearchThesisNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    issuer_id: UUID
    version: int
    text: str
    created_at: datetime


class ResearchThesisNoteCreated(ResearchThesisNoteRead):
    duplicate: bool


class ResearchWatchlistEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["added", "removed"]
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def clean_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Idempotency key cannot be blank")
        return value


class ResearchWatchlistEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issuer_id: UUID
    version: int
    action: Literal["added", "removed"]
    created_at: datetime
    duplicate: bool = False


class ResearchWatchlistRead(BaseModel):
    issuer_id: UUID
    issuer_name: str
    version: int | None
    active: bool
    changed_at: datetime | None


class ResearchBaselineSnapshot(BaseModel):
    schema_version: Literal["finance-research-baseline-v1"]
    issuer_id: UUID
    issuer_name: str
    question: str
    generated_at: datetime
    mode: Literal["offline_deterministic"]
    facts: list[ResearchFactObservation]
    citations: list[ResearchCitationRead]
    portfolio_context: ResearchPortfolioContext | None = None
    thesis_note: ResearchThesisNoteRead | None = None
    inferences: list[str]
    unknowns: list[str]


class ResearchRunRead(BaseModel):
    id: UUID
    issuer_id: UUID
    idempotency_key: str
    request_fingerprint: str
    question: str
    selected_fact_ids: list[UUID]
    state: Literal["completed"]
    created_at: datetime
    schema_version: Literal["finance-research-baseline-v1"]
    validation_status: Literal["source_links_checked_unverified_values"]
    result_hash: str
    result: ResearchBaselineSnapshot
    duplicate: bool = False
