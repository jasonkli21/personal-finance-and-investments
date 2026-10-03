"""Stage 3 OpenAPI contracts for evidence history and performance."""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.contracts import ExposureRowRead


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


class SaleLotSelection(BaseModel):
    lot_id: UUID
    quantity: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")

    @field_validator("quantity")
    @classmethod
    def selection_precision(cls, value: str) -> str:
        if len(value.split(".")[0]) > 18:
            raise ValueError("Quantity exceeds NUMERIC(28, 10) precision")
        return value


class SaleScenarioInput(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    fee_amount: str = Field(default="0", max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    selections: list[SaleLotSelection] = Field(min_length=1, max_length=100)

    @field_validator("label")
    @classmethod
    def clean_sale_label(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Scenario label cannot be blank")
        return clean

    @field_validator("fee_amount")
    @classmethod
    def fee_precision(cls, value: str) -> str:
        if len(value.split(".")[0]) > 18:
            raise ValueError("Fee exceeds NUMERIC(28, 10) precision")
        return value


class SalesSimulationRequest(BaseModel):
    account_id: UUID
    security_id: UUID
    sale_date: date
    target_type: Literal["shares", "value"]
    target_amount: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    scenarios: list[SaleScenarioInput] = Field(min_length=1, max_length=2)

    @field_validator("target_amount")
    @classmethod
    def target_precision(cls, value: str) -> str:
        if len(value.split(".")[0]) > 18:
            raise ValueError("Target exceeds NUMERIC(28, 10) precision")
        return value

    @model_validator(mode="after")
    def unique_scenario_labels(self) -> "SalesSimulationRequest":
        labels = [scenario.label.casefold() for scenario in self.scenarios]
        if len(labels) != len(set(labels)):
            raise ValueError("Scenario labels must be unique")
        return self


class SalePriceBaselineRead(BaseModel):
    account_id: UUID
    account_position_revision: int
    position_snapshot_id: UUID
    position_snapshot_revision: int
    position_snapshot_at: datetime
    position_line_id: UUID
    position_quantity: str
    security_id: UUID
    security_type: str
    ticker: str | None
    currency: str
    price: str
    price_as_of: datetime
    price_source: str
    price_source_id: UUID
    price_quality: str
    baseline_fingerprint: str


class SaleLotResultRead(BaseModel):
    lot_id: UUID
    source_lot_id: str | None
    source_label: str
    acquired_at: date | None
    quality_status: str
    selected_quantity: str
    available_quantity: str
    basis_currency: str | None
    available_basis: str | None
    selected_basis: str | None
    remaining_quantity: str
    remaining_basis: str | None
    gross_proceeds: str
    fee_allocation: str
    net_proceeds: str
    estimated_gain_loss: str | None
    holding_period_candidate: Literal["short_term", "long_term", "unknown"]


class PotentialPurchaseRead(BaseModel):
    source_type: Literal["investment_event", "tax_lot"]
    evidence_id: UUID
    account_id: UUID
    account_name: str
    effective_date: date
    quantity: str | None
    source_label: str


class PotentialWashSaleWarningRead(BaseModel):
    status: Literal["potential_match", "none_detected", "not_applicable", "unknown"]
    coverage: Literal["unknown"]
    rule_version: str
    jurisdiction: str
    window_start: date
    window_end: date
    affected_lot_ids: list[UUID]
    matches: list[PotentialPurchaseRead]
    evidence_truncated: bool
    source_url: str
    disclosure: str


class SaleScenarioResultRead(BaseModel):
    label: str
    target_shares: str
    selected_shares: str
    target_value: str | None
    value_rounding_remainder: str | None
    gross_proceeds: str
    fees: str
    net_proceeds: str
    basis_status: Literal["available", "unavailable"]
    selected_basis: str | None
    estimated_gain_loss: str | None
    remaining_position_quantity: str
    lots: list[SaleLotResultRead]
    potential_wash_sale: PotentialWashSaleWarningRead
    disclosure: list[str]


class SalesSimulationRead(BaseModel):
    methodology_version: str
    jurisdiction_policy_version: str
    account_id: UUID
    security_id: UUID
    sale_date: date
    target_type: Literal["shares", "value"]
    target_amount: str
    currency: str
    baseline: SalePriceBaselineRead
    scenarios: list[SaleScenarioResultRead]
    calculation_fingerprint: str
    canonical_records_mutated: Literal[False]
    persisted: Literal[False]
    disclosures: list[str]


class PortfolioScenarioTradeInput(BaseModel):
    account_id: UUID
    security_id: UUID
    side: Literal["buy", "sell"]
    quantity: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    price: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    fee_amount: str = Field(default="0", max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("quantity", "price", "fee_amount")
    @classmethod
    def trade_precision(cls, value: str) -> str:
        if len(value.split(".")[0]) > 18:
            raise ValueError("Trade amount exceeds NUMERIC(28, 10) precision")
        return value


class PortfolioScenarioCashInput(BaseModel):
    account_id: UUID
    amount: str = Field(max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    label: str = Field(min_length=1, max_length=100)

    @field_validator("amount")
    @classmethod
    def cash_precision(cls, value: str) -> str:
        if len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("Cash assumption exceeds NUMERIC(28, 10) precision")
        return value

    @field_validator("label")
    @classmethod
    def clean_cash_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Cash assumption label cannot be blank")
        return cleaned


class PortfolioCategoryTargetInput(BaseModel):
    category: Literal[
        "direct",
        "indirect",
        "cash",
        "opaque_fund",
        "nested_fund",
        "missing_weight",
        "unknown_other",
    ]
    target_percent: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")

    @field_validator("target_percent")
    @classmethod
    def target_precision(cls, value: str) -> str:
        if len(value.split(".")[0]) > 3 or Decimal(value) > 100:
            raise ValueError("Category target must be between 0 and 100 percent")
        return value


class PortfolioScenarioRequest(BaseModel):
    account_ids: list[UUID] = Field(default_factory=list, max_length=500)
    as_of: datetime
    financing_policy: Literal["cash_only"]
    trades: list[PortfolioScenarioTradeInput] = Field(
        default_factory=list, max_length=100
    )
    cash_changes: list[PortfolioScenarioCashInput] = Field(
        default_factory=list, max_length=100
    )
    category_targets: list[PortfolioCategoryTargetInput] = Field(
        default_factory=list, max_length=7
    )

    @field_validator("as_of")
    @classmethod
    def scenario_time_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Use an as-of time with timezone")
        return value

    @model_validator(mode="after")
    def validate_scenario_scope(self) -> "PortfolioScenarioRequest":
        if len(self.account_ids) != len(set(self.account_ids)):
            raise ValueError("Selected accounts must be unique")
        if not self.trades and not self.cash_changes:
            raise ValueError("Enter at least one hypothetical trade or cash assumption")
        trade_keys = [(row.account_id, row.security_id) for row in self.trades]
        if len(trade_keys) != len(set(trade_keys)):
            raise ValueError("Use at most one trade per account and security")
        if any(Decimal(row.amount) == 0 for row in self.cash_changes):
            raise ValueError("Cash assumptions must be nonzero")
        categories = [row.category for row in self.category_targets]
        if len(categories) != len(set(categories)):
            raise ValueError("Allocation target categories must be unique")
        if self.category_targets and sum(
            (Decimal(row.target_percent) for row in self.category_targets), Decimal(0)
        ) != Decimal(100):
            raise ValueError("Entered category targets must sum to 100 percent")
        return self


class PortfolioScenarioOverlapRead(BaseModel):
    security_id: str
    label: str
    fund_count: int
    fund_ids: list[str]
    fund_labels: list[str]
    fund_amounts: dict[str, str]
    shared_indirect_amount: str


class PortfolioScenarioDriftRead(BaseModel):
    category: str
    target_percent: str
    actual_percent: str | None
    drift_percentage_points: str | None


class PortfolioScenarioFundRead(BaseModel):
    security_id: str
    snapshot_id: str
    as_of: date
    source: str
    source_url: str | None
    quality_status: str
    stale: bool


class PortfolioExposureSnapshotRead(BaseModel):
    included_valued_nav: str
    total_portfolio_nav: str | None
    nav_status: Literal["complete", "incomplete"]
    percentages_available: bool
    direct_assets: str
    indirect_lookthrough: str
    residual: str
    residual_categories: dict[str, str]
    opaque_and_unknown_value: str
    categories: dict[str, str]
    reconciled: bool
    security_rows: list[ExposureRowRead]
    issuer_rows: list[ExposureRowRead]
    overlap_rows: list[PortfolioScenarioOverlapRead]
    shared_indirect_amount: str
    drift_status: Literal["available", "unavailable", "not_requested"]
    drift_rows: list[PortfolioScenarioDriftRead]
    fund_snapshots: list[PortfolioScenarioFundRead]
    warnings: list[str]


class PortfolioScenarioTradeRead(BaseModel):
    account_id: UUID
    account_name: str
    security_id: UUID
    ticker: str | None
    side: Literal["buy", "sell"]
    quantity: str
    quantity_before: str
    quantity_after: str
    execution_price: str
    currency: str
    gross_amount: str
    fee_amount: str
    cash_delta: str
    market_value_before: str
    market_value_after: str
    valuation_price_source: str


class PortfolioScenarioCashRead(BaseModel):
    account_id: UUID
    account_name: str
    currency: str
    cash_before: str
    assumption_delta: str
    trade_delta: str
    cash_after: str


class PortfolioScenarioCashAssumptionRead(BaseModel):
    account_id: UUID
    account_name: str
    amount: str
    currency: Literal["USD"]
    label: str


class PortfolioScenarioRead(BaseModel):
    methodology_version: str
    exposure_calculation_version: str
    as_of: datetime
    account_ids: list[UUID]
    account_names: list[str]
    account_position_revisions: dict[str, int]
    position_snapshot_ids: dict[str, UUID]
    financing_policy: Literal["cash_only"]
    currency: Literal["USD"]
    before: PortfolioExposureSnapshotRead
    after: PortfolioExposureSnapshotRead
    trades: list[PortfolioScenarioTradeRead]
    cash: list[PortfolioScenarioCashRead]
    cash_changes: list[PortfolioScenarioCashAssumptionRead]
    baseline_fingerprint: str
    scenario_fingerprint: str
    canonical_records_mutated: Literal[False]
    persisted: Literal[False]
    assumptions: list[str]


class PlanningRecurringChangeInput(BaseModel):
    amount: str = Field(max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$")
    label: str = Field(min_length=1, max_length=100)

    @field_validator("amount")
    @classmethod
    def recurring_precision(cls, value: str) -> str:
        if len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("Recurring change exceeds NUMERIC(28, 10) precision")
        if Decimal(value) == 0:
            raise ValueError("Recurring changes must be nonzero")
        return value

    @field_validator("label")
    @classmethod
    def trim_recurring_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Recurring change label cannot be blank")
        return normalized


class PlanningOneTimeChangeInput(BaseModel):
    month_offset: int = Field(ge=1, le=120)
    change_type: Literal["purchase", "liability_payment", "other"]
    amount: str = Field(max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$")
    label: str = Field(min_length=1, max_length=100)

    @field_validator("amount")
    @classmethod
    def one_time_precision(cls, value: str) -> str:
        if len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("One-time change exceeds NUMERIC(28, 10) precision")
        if Decimal(value) == 0:
            raise ValueError("One-time changes must be nonzero")
        return value

    @field_validator("label")
    @classmethod
    def trim_one_time_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("One-time change label cannot be blank")
        return normalized

    @model_validator(mode="after")
    def enforce_outflow_sign(self) -> "PlanningOneTimeChangeInput":
        if (
            self.change_type in {"purchase", "liability_payment"}
            and Decimal(self.amount) > 0
        ):
            raise ValueError("Purchases and liability payments must reduce cash")
        return self


class PlanningScenarioRequest(BaseModel):
    account_ids: list[UUID] = Field(default_factory=list, max_length=100)
    as_of: date
    horizon_months: int = Field(ge=1, le=120)
    history_months: int = Field(ge=1, le=60)
    monthly_income: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    monthly_income_source: str = Field(min_length=1, max_length=100)
    monthly_expenses: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    monthly_expenses_source: str = Field(min_length=1, max_length=100)
    monthly_dividends: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    monthly_dividends_source: str = Field(min_length=1, max_length=100)
    sensitivity_percent: str = Field(max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$")
    starting_cash_override: str | None = Field(
        default=None, max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$"
    )
    recurring_changes: list[PlanningRecurringChangeInput] = Field(
        default_factory=list, max_length=20
    )
    one_time_changes: list[PlanningOneTimeChangeInput] = Field(
        default_factory=list, max_length=100
    )
    scenario_label: str = Field(min_length=1, max_length=100)

    @field_validator(
        "monthly_income",
        "monthly_expenses",
        "monthly_dividends",
        "starting_cash_override",
    )
    @classmethod
    def planning_amount_precision(cls, value: str | None) -> str | None:
        if value is not None and len(value.split(".")[0]) > 18:
            raise ValueError("Planning amount exceeds NUMERIC(28, 10) precision")
        return value

    @field_validator("sensitivity_percent")
    @classmethod
    def bounded_sensitivity(cls, value: str) -> str:
        amount = Decimal(value)
        if amount > 50:
            raise ValueError("Sensitivity must be between 0 and 50 percent")
        return value

    @field_validator(
        "monthly_income_source",
        "monthly_expenses_source",
        "monthly_dividends_source",
        "scenario_label",
    )
    @classmethod
    def trim_assumption_labels(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Planning labels cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_scope(self) -> "PlanningScenarioRequest":
        if len(self.account_ids) != len(set(self.account_ids)):
            raise ValueError("Selected accounts must be unique")
        if any(row.month_offset > self.horizon_months for row in self.one_time_changes):
            raise ValueError("One-time changes must fall within the projection horizon")
        return self


class PlanningAccountLineRead(BaseModel):
    account_id: UUID
    account_name: str
    account_type: str
    position_snapshot_id: UUID | None = None
    position_revision: int | None = None
    account_balance_id: UUID | None = None
    balance_revision: int | None = None
    as_of: date | None
    price_as_of: datetime | None = None
    currency: str | None
    amount: str | None
    bucket: Literal[
        "liquid_cash",
        "investment",
        "restricted_asset",
        "other_asset",
        "liability",
        "foreign_asset",
        "unavailable",
        "excluded",
    ]
    source: str | None
    quality_status: str
    status: str
    detail: str | None
    included_in_starting_cash: bool


class PlanningCurrencyBalanceRead(BaseModel):
    currency: str
    liquid_cash: str
    investment_assets: str
    restricted_assets: str
    other_assets: str
    liabilities: str
    known_net_worth: str
    completeness: Literal["complete", "incomplete"]


class PlanningTransactionHistoryRead(BaseModel):
    currency: str
    source_labels: list[str]
    income_total: str
    expenses_total: str
    net_cash_flow: str
    income_monthly_average: str | None
    expenses_monthly_average: str | None
    published_transaction_count: int
    classified_transaction_count: int
    unclassified_count: int
    unclassified_signed_amount: str


class PlanningDividendHistoryRead(BaseModel):
    currency: str
    total: str
    monthly_average: str
    event_count: int
    source_labels: list[str]


class PlanningProjectionMonthRead(BaseModel):
    month_index: int
    month_start: date
    starting_cash: str
    income: str
    expenses: str
    dividends: str
    recurring_changes: str
    one_time_changes: str
    ending_cash: str


class PlanningProjectionCaseRead(BaseModel):
    case: Literal["conservative", "base", "optimistic"]
    starting_cash: str
    ending_cash: str
    shortfall_month: int | None
    runway_status: Literal[
        "shortfall_within_horizon", "beyond_horizon", "coverage_incomplete"
    ]
    months: list[PlanningProjectionMonthRead]


class PlanningScenarioRead(BaseModel):
    methodology_version: str
    scenario_label: str
    as_of: date
    projection_start: date
    horizon_months: int
    history_start: date
    history_end: date
    account_ids: list[UUID]
    account_names: list[str]
    account_position_revisions: dict[str, int]
    position_snapshot_ids: dict[str, UUID]
    account_balance_revisions: dict[str, int]
    account_balance_ids: dict[str, UUID]
    balances: list[PlanningAccountLineRead]
    currency_balances: list[PlanningCurrencyBalanceRead]
    balance_sheet_complete: bool
    liquid_cash_observed_usd: str
    starting_cash_usd: str
    starting_cash_source: Literal["observed_usd_cash", "user_override"]
    starting_cash_coverage: Literal["complete", "incomplete", "user_assumed"]
    transaction_history: list[PlanningTransactionHistoryRead]
    dividend_history: list[PlanningDividendHistoryRead]
    history_gaps: list[str]
    monthly_income_assumption: str
    monthly_income_source: str
    monthly_expense_assumption: str
    monthly_expenses_source: str
    monthly_dividend_assumption: str
    monthly_dividends_source: str
    sensitivity_percent: str
    recurring_changes: list[PlanningRecurringChangeInput]
    one_time_changes: list[PlanningOneTimeChangeInput]
    projection_status: Literal["available", "incomplete"]
    cases: list[PlanningProjectionCaseRead]
    warnings: list[str]
    scenario_fingerprint: str
    canonical_records_mutated: Literal[False]
    persisted: Literal[False]
