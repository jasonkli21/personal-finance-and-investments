"""Stage 3 OpenAPI contracts for evidence history and performance."""

import json
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InvestmentEventCreate(BaseModel):
    account_id: UUID
    security_id: UUID | None = None
    event_type: Literal[
        "buy",
        "sell",
        "dividend",
        "fee",
        "deposit",
        "withdrawal",
        "transfer_in",
        "transfer_out",
        "split",
        "adjustment",
        "other",
    ]
    effective_date: date
    quantity_delta: str | None = Field(
        default=None, max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$"
    )
    cash_amount: str | None = Field(
        default=None, max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$"
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    source_label: str = Field(min_length=1, max_length=100)
    source_event_id: str | None = Field(default=None, max_length=200)
    evidence_ref: str | None = Field(default=None, max_length=500)
    quality_status: Literal["reported", "manual", "estimated", "unknown"] = "reported"
    idempotency_key: str = Field(min_length=1, max_length=128)
    raw_values: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_label")
    @classmethod
    def clean_source_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Source label cannot be blank")
        return value

    @field_validator("quantity_delta", "cash_amount")
    @classmethod
    def financial_precision(cls, value: str | None) -> str | None:
        if value is not None and len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("Amount exceeds NUMERIC(28, 10) precision")
        return value

    @field_validator("raw_values")
    @classmethod
    def bound_raw_values(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, separators=(",", ":")).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("Raw event values must be JSON-compatible") from exc
        if len(encoded) > 16_384:
            raise ValueError("Raw event values exceed the 16 KiB metadata limit")
        return value


class InvestmentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    security_id: UUID | None
    event_type: str
    effective_date: date
    quantity_delta: str | None
    cash_amount: str | None
    currency: str
    is_external_flow: bool
    source_label: str
    source_event_id: str | None
    evidence_ref: str | None
    quality_status: str
    review_status: str
    idempotency_key: str
    created_at: datetime

    @field_validator("quantity_delta", "cash_amount", mode="before")
    @classmethod
    def decimal_to_string(cls, value: Any) -> Any:
        return str(value) if value is not None else None


class HistorySnapshotRead(BaseModel):
    id: UUID
    effective_date: date
    revision: int
    source: str
    status: str
    accepted_at: datetime | None
    line_count: int


class PortfolioHistoryRead(BaseModel):
    account_id: UUID
    start_date: date
    end_date: date
    snapshots: list[HistorySnapshotRead]
    events: list[InvestmentEventRead]
    methodology: str


class PortfolioPerformanceRead(BaseModel):
    account_id: UUID
    start_date: date
    end_date: date
    status: Literal["available", "unavailable"]
    currency: str
    beginning_value: str | None
    ending_value: str | None
    time_weighted_return: str | None
    time_weighted_method: str
    money_weighted_return: str | None
    money_weighted_status: str
    methodology_version: str
    observation_count: int
    external_flow_count: int
    observed_dates: list[date]
    diagnostics: list[str]


class ReconciliationDifference(BaseModel):
    security_id: UUID
    ticker: str | None
    expected_quantity: str
    snapshot_quantity: str
    difference: str


class HistoryReconciliationRead(BaseModel):
    status: Literal["matched", "discrepancy", "unavailable"]
    account_id: UUID
    start_date: date
    end_date: date
    differences: list[ReconciliationDifference]
    gaps: list[str]
    methodology: str | None = None


class TaxLotImportCreated(BaseModel):
    id: UUID
    status: str
    row_count: int
    review_revision: int
    duplicate: bool


class TaxLotImportRowRead(BaseModel):
    id: UUID
    row_number: int
    raw_payload: dict[str, Any]
    raw_ticker: str | None
    raw_source_lot_id: str | None
    security_id: UUID | None
    ticker: str | None
    acquired_at: date | None
    initial_quantity: str | None
    remaining_quantity: str | None
    initial_basis: str | None
    remaining_basis: str | None
    basis_currency: str | None
    evidence_ref: str | None
    quality_status: str
    row_status: str
    diagnostics: dict[str, Any]
    tax_lot_id: UUID | None = None


class TaxLotQuantityDifference(BaseModel):
    security_id: UUID
    ticker: str | None
    position_quantity: str | None
    lot_quantity: str
    difference: str | None


class TaxLotImportReviewRead(BaseModel):
    id: UUID
    account_id: UUID
    source_label: str
    file_sha256: str
    status: str
    review_revision: int
    row_count: int
    diagnostics: dict[str, Any]
    rows: list[TaxLotImportRowRead]
    quantity_differences: list[TaxLotQuantityDifference]
    gaps: list[str]


class TaxLotImportCorrection(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    security_id: UUID | None = None
    source_lot_id: str | None = Field(default=None, max_length=200)
    acquired_at: date | None = None
    initial_quantity: str | None = Field(
        default=None, max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$"
    )
    remaining_quantity: str | None = Field(
        default=None, max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$"
    )
    initial_basis: str | None = Field(
        default=None, max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$"
    )
    remaining_basis: str | None = Field(
        default=None, max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$"
    )
    basis_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    evidence_ref: str | None = Field(default=None, max_length=500)

    @field_validator(
        "initial_quantity", "remaining_quantity", "initial_basis", "remaining_basis"
    )
    @classmethod
    def lot_value_precision(cls, value: str | None) -> str | None:
        if value is not None and len(value.split(".")[0]) > 18:
            raise ValueError("Value exceeds NUMERIC(28, 10) precision")
        return value

    @model_validator(mode="after")
    def require_correction(self) -> "TaxLotImportCorrection":
        if not set(self.model_fields_set).difference({"expected_revision", "reason"}):
            raise ValueError("At least one lot field must be corrected")
        return self


class TaxLotImportPublish(BaseModel):
    expected_revision: int = Field(ge=1)
    acknowledge_quantity_differences: bool = False
    reason: str = Field(min_length=1, max_length=500)


class TaxLotAdjustmentCreate(BaseModel):
    adjustment_type: Literal[
        "split", "basis_adjustment", "return_of_capital", "correction", "other"
    ]
    quantity_delta: str | None = Field(
        default=None, max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$"
    )
    basis_delta: str | None = Field(
        default=None, max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$"
    )
    basis_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    effective_date: date
    source_label: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    evidence_ref: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)
    raw_values: dict[str, Any] = Field(default_factory=dict)

    @field_validator("quantity_delta", "basis_delta")
    @classmethod
    def adjustment_precision(cls, value: str | None) -> str | None:
        if value is not None and len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("Adjustment exceeds NUMERIC(28, 10) precision")
        return value

    @field_validator("source_label", "reason")
    @classmethod
    def trim_adjustment_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value cannot be blank")
        return cleaned

    @field_validator("raw_values")
    @classmethod
    def bound_adjustment_raw_values(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, separators=(",", ":")).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("Raw adjustment values must be JSON-compatible") from exc
        if len(encoded) > 16_384:
            raise ValueError("Raw adjustment values exceed the 16 KiB metadata limit")
        return value

    @model_validator(mode="after")
    def require_adjustment_value(self) -> "TaxLotAdjustmentCreate":
        if self.quantity_delta is None and self.basis_delta is None:
            raise ValueError("Supply a quantity or basis adjustment")
        if self.quantity_delta == "0" and self.basis_delta == "0":
            raise ValueError("An adjustment must change a value")
        return self


class TaxLotAdjustmentRead(BaseModel):
    id: UUID
    tax_lot_id: UUID
    adjustment_type: str
    quantity_delta: str | None
    basis_delta: str | None
    basis_currency: str | None
    effective_date: date
    source_label: str
    reason: str
    evidence_ref: str | None
    created_at: datetime


class TaxLotRead(BaseModel):
    id: UUID
    account_id: UUID
    security_id: UUID
    ticker: str | None
    security_name: str
    import_id: UUID
    source_label: str
    source_lot_id: str | None
    acquired_at: date | None
    initial_quantity: str | None
    remaining_quantity: str
    current_remaining_quantity: str
    initial_basis: str | None
    remaining_basis: str | None
    current_remaining_basis: str | None
    basis_currency: str | None
    evidence_ref: str | None
    quality_status: str
    adjustments: list[TaxLotAdjustmentRead]
