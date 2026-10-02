"""Public API contracts for accounts, local security lookup and positions."""

from datetime import date, datetime
from typing import Literal
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


class ImportRowRead(BaseModel):
    id: UUID
    row_number: int
    raw_payload: dict[str, str]
    raw_identifier: str | None
    raw_name: str | None
    raw_asset_type: str | None
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
