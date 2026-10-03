"""Finance-owned, versioned contracts for offline public-research records."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
