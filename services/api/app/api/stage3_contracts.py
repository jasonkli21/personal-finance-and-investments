"""Stage 3 OpenAPI contracts for evidence history and performance."""

import json
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
