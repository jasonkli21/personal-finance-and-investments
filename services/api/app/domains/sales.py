"""Read-only, source-frozen hypothetical lot-sale calculations."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext
from typing import Any
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.api.stage3_contracts import SalesSimulationRequest
from app.db.models import (
    Account,
    InvestmentEvent,
    PositionSnapshot,
    PositionSnapshotLine,
    Quote,
    Security,
    TaxLot,
    TaxLotAdjustment,
)
from app.domains.tax import lot_state
from app.providers.quotes import observation_time

SALE_METHOD_VERSION = "hypothetical-lot-sale-v1"
US_TAX_POLICY_VERSION = "us-federal-pub550-2025-holding-period-wash-sale-v1"
WASH_SALE_SOURCE = "https://www.irs.gov/publications/p550"
MONEY_QUANTUM = Decimal("0.0000000001")
SHARE_QUANTUM = Decimal("0.0000000001")
MAX_AMOUNT = Decimal("1e18")
MAX_EVIDENCE_ROWS = 500


class SalesSimulationError(ValueError):
    """The requested hypothetical sale cannot be calculated safely."""


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _digest(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _holding_period_candidate(acquired_at: date | None, sale_date: date) -> str:
    if acquired_at is None or acquired_at > sale_date:
        return "unknown"
    # The source rule has edge cases for leap dates and special acquisition
    # histories. Keep leap-day anniversaries unknown instead of guessing.
    if acquired_at.month == 2 and acquired_at.day == 29:
        return "unknown"
    try:
        anniversary = acquired_at.replace(year=acquired_at.year + 1)
    except ValueError:
        return "unknown"
    return "long_term" if sale_date > anniversary else "short_term"


def _baseline(
    session: Session, request: SalesSimulationRequest
) -> tuple[dict[str, Any], Account, Security, Decimal, Decimal]:
    account = session.get(Account, request.account_id)
    if account is None or not account.active:
        raise SalesSimulationError("Active account not found.")
    if account.current_position_snapshot_id is None:
        raise SalesSimulationError(
            "No accepted current position snapshot is available."
        )
    snapshot = session.get(PositionSnapshot, account.current_position_snapshot_id)
    if snapshot is None or snapshot.status != "accepted":
        raise SalesSimulationError(
            "The account has no accepted current position snapshot."
        )
    snapshot_date = observation_time(snapshot.snapshot_at).date()
    if request.sale_date < snapshot_date:
        raise SalesSimulationError(
            "Sale date cannot predate the current accepted position snapshot."
        )
    if (date.today() - snapshot_date).days > 7:
        raise SalesSimulationError(
            "The accepted position snapshot is more than 7 days old. "
            "Refresh the position first."
        )

    security = session.get(Security, request.security_id)
    if security is None:
        raise SalesSimulationError("Security not found.")
    if security.security_type not in {"equity", "etf"}:
        raise SalesSimulationError(
            "Hypothetical lot sales support owned equities and ETFs only."
        )
    line = session.scalar(
        select(PositionSnapshotLine).where(
            PositionSnapshotLine.snapshot_id == snapshot.id,
            PositionSnapshotLine.security_id == security.id,
        )
    )
    if line is None or line.quantity <= 0:
        raise SalesSimulationError(
            "The selected security has no positive actual position."
        )
    if line.currency != security.currency:
        raise SalesSimulationError(
            "Accepted position currency does not match the security."
        )

    price = line.reported_price
    price_as_of = snapshot.snapshot_at
    price_source = line.source
    price_source_id = line.id
    price_quality = line.quality_status
    if price is None:
        quote = session.scalar(
            select(Quote)
            .where(
                Quote.security_id == security.id,
                Quote.currency == security.currency,
                Quote.as_of <= snapshot.snapshot_at,
            )
            .order_by(
                Quote.as_of.desc(),
                case((Quote.quality_status == "reviewed", 1), else_=0).desc(),
                Quote.source.asc(),
                Quote.id.asc(),
            )
            .limit(1)
        )
        if quote is None:
            raise SalesSimulationError(
                "A source-backed price is unavailable for this position."
            )
        price = quote.price
        price_as_of = quote.as_of
        price_source = quote.source
        price_source_id = quote.id
        price_quality = quote.quality_status

    if price <= 0:
        raise SalesSimulationError("Sale price must be positive.")
    if price_quality in {"stale", "estimated"}:
        raise SalesSimulationError(
            f"The selected sale price is {price_quality}; refresh or review "
            "the valuation first."
        )
    snapshot_time = snapshot.snapshot_at
    quote_time = price_as_of
    if snapshot_time.tzinfo is None:
        snapshot_time = snapshot_time.replace(tzinfo=UTC)
    if quote_time.tzinfo is None:
        quote_time = quote_time.replace(tzinfo=UTC)
    if snapshot_time - quote_time > timedelta(days=7):
        raise SalesSimulationError("The selected sale price is more than 7 days old.")

    baseline = {
        "account_id": account.id,
        "account_position_revision": account.current_position_revision,
        "position_snapshot_id": snapshot.id,
        "position_snapshot_revision": snapshot.revision,
        "position_snapshot_at": snapshot.snapshot_at,
        "position_line_id": line.id,
        "position_quantity": str(line.quantity),
        "security_id": security.id,
        "security_type": security.security_type,
        "ticker": security.display_ticker,
        "currency": line.currency,
        "price": str(price),
        "price_as_of": price_as_of,
        "price_source": price_source,
        "price_source_id": price_source_id,
        "price_quality": price_quality,
    }
    return baseline, account, security, Decimal(line.quantity), Decimal(price)


def _current_lots(
    session: Session,
    request: SalesSimulationRequest,
    selection_ids: set[UUID],
) -> tuple[
    dict[UUID, TaxLot],
    dict[UUID, tuple[Decimal, Decimal | None]],
    dict[UUID, list[UUID]],
]:
    rows = list(
        session.scalars(
            select(TaxLot).where(
                TaxLot.id.in_(selection_ids),
                TaxLot.account_id == request.account_id,
                TaxLot.security_id == request.security_id,
            )
        )
    )
    lots = {row.id: row for row in rows}
    if lots.keys() != selection_ids:
        raise SalesSimulationError(
            "Every selected lot must belong to the selected account and security."
        )

    adjustment_rows = list(
        session.scalars(
            select(TaxLotAdjustment)
            .where(
                TaxLotAdjustment.tax_lot_id.in_(selection_ids),
                TaxLotAdjustment.effective_date <= request.sale_date,
            )
            .order_by(
                TaxLotAdjustment.effective_date,
                TaxLotAdjustment.created_at,
                TaxLotAdjustment.id,
            )
            .limit(10_001)
        )
    )
    if len(adjustment_rows) > 10_000:
        raise SalesSimulationError(
            "Selected lot adjustment history exceeds 10,000 rows."
        )
    grouped: dict[UUID, list[TaxLotAdjustment]] = defaultdict(list)
    adjustment_ids: dict[UUID, list[UUID]] = defaultdict(list)
    for row in adjustment_rows:
        grouped[row.tax_lot_id].append(row)
        adjustment_ids[row.tax_lot_id].append(row.id)
    states = {
        lot_id: lot_state(lot, grouped.get(lot_id, [])) for lot_id, lot in lots.items()
    }
    return lots, states, adjustment_ids


def _wash_sale_warning(
    session: Session,
    *,
    security_id: UUID,
    sale_date: date,
    affected_lot_ids: list[UUID],
    loss_status_known: bool,
) -> dict[str, Any]:
    start = sale_date - timedelta(days=30)
    end = sale_date + timedelta(days=30)
    matches: list[dict[str, Any]] = []
    truncated = False
    if affected_lot_ids or not loss_status_known:
        events = list(
            session.execute(
                select(InvestmentEvent, Account)
                .join(Account, InvestmentEvent.account_id == Account.id)
                .where(
                    InvestmentEvent.security_id == security_id,
                    InvestmentEvent.event_type == "buy",
                    InvestmentEvent.quantity_delta > 0,
                    InvestmentEvent.effective_date >= start,
                    InvestmentEvent.effective_date <= end,
                    InvestmentEvent.review_status == "reviewed",
                    InvestmentEvent.quality_status.in_(("reported", "manual")),
                )
                .order_by(InvestmentEvent.effective_date, InvestmentEvent.id)
                .limit(MAX_EVIDENCE_ROWS + 1)
            )
        )
        if len(events) > MAX_EVIDENCE_ROWS:
            truncated = True
            events = events[:MAX_EVIDENCE_ROWS]
        for event, account in events:
            matches.append(
                {
                    "source_type": "investment_event",
                    "evidence_id": event.id,
                    "account_id": account.id,
                    "account_name": account.name,
                    "effective_date": event.effective_date,
                    "quantity": _text(event.quantity_delta),
                    "source_label": event.source_label,
                }
            )

        lots = list(
            session.execute(
                select(TaxLot, Account)
                .join(Account, TaxLot.account_id == Account.id)
                .where(
                    TaxLot.security_id == security_id,
                    TaxLot.acquired_at >= start,
                    TaxLot.acquired_at <= end,
                )
                .order_by(TaxLot.acquired_at, TaxLot.id)
                .limit(MAX_EVIDENCE_ROWS + 1)
            )
        )
        if len(lots) > MAX_EVIDENCE_ROWS:
            truncated = True
            lots = lots[:MAX_EVIDENCE_ROWS]
        for lot, account in lots:
            matches.append(
                {
                    "source_type": "tax_lot",
                    "evidence_id": lot.id,
                    "account_id": account.id,
                    "account_name": account.name,
                    "effective_date": lot.acquired_at,
                    "quantity": _text(lot.initial_quantity),
                    "source_label": lot.source_label,
                }
            )

    if affected_lot_ids:
        status = "potential_match" if matches else "none_detected"
    else:
        status = "not_applicable" if loss_status_known else "unknown"
    return {
        "status": status,
        "coverage": "unknown",
        "rule_version": US_TAX_POLICY_VERSION,
        "jurisdiction": "United States federal; source-backed records in this database",
        "window_start": start,
        "window_end": end,
        "affected_lot_ids": affected_lot_ids,
        "matches": matches,
        "evidence_truncated": truncated,
        "source_url": WASH_SALE_SOURCE,
        "disclosure": (
            "Potential overlap uses exact local security IDs and reviewed buy "
            "events or recorded lot acquisition dates. Coverage is unknown: "
            "outside accounts, spouse activity, options, and other securities "
            "are not represented; no match is not tax-compliance clearance. "
            "This is not a legal determination."
        ),
    }


def simulate_sales(session: Session, request: SalesSimulationRequest) -> dict[str, Any]:
    """Return up to two sale comparisons without writing canonical records."""
    target_amount = Decimal(request.target_amount)
    if target_amount <= 0:
        raise SalesSimulationError("Sale target must be positive.")

    with localcontext() as context:
        context.prec = 80
        baseline, _account, security, position_quantity, price = _baseline(
            session, request
        )
        if request.target_type == "shares":
            target_shares = target_amount.quantize(SHARE_QUANTUM)
            target_value = None
        else:
            target_shares = (target_amount / price).quantize(
                SHARE_QUANTUM, rounding=ROUND_DOWN
            )
            if target_shares <= 0:
                raise SalesSimulationError("Value target rounds down to zero shares.")
            target_value = target_amount
        if target_shares > position_quantity:
            raise SalesSimulationError(
                "Sale target exceeds the accepted actual position."
            )

        selection_ids = {
            selection.lot_id
            for scenario in request.scenarios
            for selection in scenario.selections
        }
        if sum(len(scenario.selections) for scenario in request.scenarios) > 200:
            raise SalesSimulationError(
                "At most 200 lot selections are allowed across scenarios."
            )
        lots, lot_states, adjustment_ids = _current_lots(
            session, request, selection_ids
        )

        lot_inputs: list[dict[str, Any]] = []
        for lot_id in sorted(lots, key=str):
            lot = lots[lot_id]
            current_quantity, current_basis = lot_states[lot_id]
            if current_quantity <= 0 or current_basis is not None and current_basis < 0:
                raise SalesSimulationError(
                    "A selected lot has a nonpositive quantity or invalid basis."
                )
            lot_inputs.append(
                {
                    "lot_id": lot.id,
                    "source_lot_id": lot.source_lot_id,
                    "account_id": lot.account_id,
                    "security_id": lot.security_id,
                    "acquired_at": lot.acquired_at,
                    "quantity": current_quantity,
                    "basis": current_basis,
                    "basis_currency": lot.basis_currency,
                    "quality_status": lot.quality_status,
                    "adjustment_ids": adjustment_ids.get(lot_id, []),
                }
            )
        baseline_fingerprint = _digest(
            {
                "baseline": baseline,
                "sale_date": request.sale_date,
                "lots": lot_inputs,
            }
        )
        baseline["baseline_fingerprint"] = baseline_fingerprint

        scenario_results: list[dict[str, Any]] = []
        warning_evidence: list[Any] = []
        for scenario in request.scenarios:
            seen: set[UUID] = set()
            selected_quantities: list[tuple[UUID, Decimal]] = []
            for selection in scenario.selections:
                if selection.lot_id in seen:
                    raise SalesSimulationError(
                        "A lot may only be selected once per scenario."
                    )
                seen.add(selection.lot_id)
                quantity = Decimal(selection.quantity)
                available, _basis = lot_states[selection.lot_id]
                if quantity <= 0:
                    raise SalesSimulationError(
                        "Selected lot quantities must be positive."
                    )
                if quantity > available:
                    raise SalesSimulationError(
                        "Selected quantity exceeds that lot's available shares."
                    )
                acquired_at = lots[selection.lot_id].acquired_at
                if acquired_at is not None and acquired_at > request.sale_date:
                    raise SalesSimulationError(
                        "Sale date precedes a selected lot's acquisition date."
                    )
                selected_quantities.append((selection.lot_id, quantity))

            selected_total = sum((item[1] for item in selected_quantities), Decimal(0))
            if selected_total != target_shares:
                raise SalesSimulationError(
                    "Explicit lot selections must sum exactly to the share target "
                    "(including value-target rounding)."
                )
            fee = Decimal(scenario.fee_amount)
            if fee < 0:
                raise SalesSimulationError("Fees cannot be negative.")
            gross = _rounded(selected_total * price)
            if gross <= 0:
                raise SalesSimulationError(
                    "Sale proceeds round to zero at 10 decimal places."
                )
            if fee > gross:
                raise SalesSimulationError("Fees cannot exceed gross sale proceeds.")

            raw_lines: list[dict[str, Any]] = []
            total_basis = Decimal(0)
            all_basis_available = True
            known_losses: list[UUID] = []
            unknown_loss_status = False
            for lot_id, quantity in selected_quantities:
                lot = lots[lot_id]
                available_quantity, available_basis = lot_states[lot_id]
                if available_basis is None or lot.basis_currency != security.currency:
                    all_basis_available = False
                    selected_basis = None
                    remaining_basis = available_basis
                    gain = None
                    unknown_loss_status = True
                else:
                    selected_basis = (
                        available_basis
                        if quantity == available_quantity
                        else _rounded(available_basis * quantity / available_quantity)
                    )
                    remaining_basis = available_basis - selected_basis
                    total_basis += selected_basis
                    gain = None
                raw_lines.append(
                    {
                        "lot": lot,
                        "lot_id": lot_id,
                        "quantity": quantity,
                        "available_quantity": available_quantity,
                        "available_basis": available_basis,
                        "selected_basis": selected_basis,
                        "remaining_basis": remaining_basis,
                        "gain": gain,
                        "gross_proceeds": _rounded(quantity * price),
                    }
                )

            gross_left = gross
            fee_left = fee
            for index, line in enumerate(raw_lines):
                if index == len(raw_lines) - 1:
                    line_gross = gross_left
                else:
                    line_gross = min(line["gross_proceeds"], gross_left)
                    gross_left -= line_gross
                if index == len(raw_lines) - 1:
                    line_fee = fee_left
                else:
                    line_fee = min(
                        _rounded(fee * line["quantity"] / selected_total), fee_left
                    )
                    fee_left -= line_fee
                line["gross_proceeds"] = line_gross
                line["fee"] = line_fee
                line["net_proceeds"] = line["gross_proceeds"] - line_fee
                if line["selected_basis"] is not None:
                    line["gain"] = line["net_proceeds"] - line["selected_basis"]
                    if line["gain"] < 0:
                        known_losses.append(line["lot_id"])

            basis_available = all_basis_available
            total_gain = (
                sum((line["gain"] for line in raw_lines), Decimal(0))
                if basis_available
                else None
            )
            if any(
                abs(amount) >= MAX_AMOUNT
                for amount in (gross, fee, gross - fee, total_basis, total_gain)
                if amount is not None
            ):
                raise SalesSimulationError(
                    "Sale proceeds or basis exceed NUMERIC(28, 10) precision."
                )
            if not basis_available:
                unknown_loss_status = True
            warning = _wash_sale_warning(
                session,
                security_id=request.security_id,
                sale_date=request.sale_date,
                affected_lot_ids=known_losses,
                loss_status_known=not unknown_loss_status,
            )
            warning_evidence.append(
                {
                    "status": warning["status"],
                    "matches": warning["matches"],
                    "affected_lot_ids": warning["affected_lot_ids"],
                    "truncated": warning["evidence_truncated"],
                }
            )
            line_results = []
            for line in raw_lines:
                lot = line["lot"]
                line_results.append(
                    {
                        "lot_id": lot.id,
                        "source_lot_id": lot.source_lot_id,
                        "source_label": lot.source_label,
                        "acquired_at": lot.acquired_at,
                        "quality_status": lot.quality_status,
                        "selected_quantity": _text(line["quantity"]),
                        "available_quantity": _text(line["available_quantity"]),
                        "basis_currency": lot.basis_currency,
                        "available_basis": _text(line["available_basis"]),
                        "selected_basis": _text(line["selected_basis"]),
                        "remaining_quantity": _text(
                            line["available_quantity"] - line["quantity"]
                        ),
                        "remaining_basis": _text(line["remaining_basis"]),
                        "gross_proceeds": _text(line["gross_proceeds"]),
                        "fee_allocation": _text(line["fee"]),
                        "net_proceeds": _text(line["net_proceeds"]),
                        "estimated_gain_loss": _text(line["gain"]),
                        "holding_period_candidate": _holding_period_candidate(
                            lot.acquired_at, request.sale_date
                        ),
                    }
                )
            disclosure = [
                (
                    "This is a hypothetical estimate; it does not create or "
                    "update positions, transactions, lots, or adjustments."
                ),
                (
                    "Per-lot basis is allocated in proportion to selected "
                    "quantity and rounded to 10 decimal places; a full-lot "
                    "sale uses the entire remaining basis."
                ),
                (
                    "The latest reported price on the accepted snapshot is "
                    "held constant through the hypothetical sale date; future "
                    "market prices are not forecast."
                ),
                (
                    "Holding-period labels are ordinary U.S. federal "
                    "candidates based on the recorded acquisition date only; "
                    "exceptions and prior holding-period tacking are not "
                    "modeled."
                ),
            ]
            scenario_results.append(
                {
                    "label": scenario.label,
                    "target_shares": _text(target_shares),
                    "selected_shares": _text(selected_total),
                    "target_value": _text(target_value),
                    "value_rounding_remainder": (
                        _text(_rounded(target_amount - gross))
                        if request.target_type == "value"
                        else None
                    ),
                    "gross_proceeds": _text(gross),
                    "fees": _text(fee),
                    "net_proceeds": _text(gross - fee),
                    "basis_status": "available" if basis_available else "unavailable",
                    "selected_basis": _text(total_basis) if basis_available else None,
                    "estimated_gain_loss": _text(total_gain),
                    "remaining_position_quantity": _text(
                        position_quantity - selected_total
                    ),
                    "lots": line_results,
                    "potential_wash_sale": warning,
                    "disclosure": disclosure,
                }
            )

        if (
            len(request.scenarios) == 2
            and len({result["target_shares"] for result in scenario_results}) != 1
        ):
            raise SalesSimulationError(
                "Compared scenarios must use the same sale target."
            )
        if (
            abs(target_shares * price) >= MAX_AMOUNT
            or abs(target_shares * price - target_amount) >= MAX_AMOUNT
        ):
            raise SalesSimulationError("Sale value exceeds NUMERIC(28, 10) precision.")

        calculation_fingerprint = _digest(
            {
                "methodology_version": SALE_METHOD_VERSION,
                "jurisdiction_policy_version": US_TAX_POLICY_VERSION,
                "baseline_fingerprint": baseline_fingerprint,
                "request": request.model_dump(mode="json"),
                "warning_evidence": warning_evidence,
            }
        )
        disclosures = [
            "Scenarios are derived read-only outputs and are not persisted.",
            (
                "A matching purchase warning is potential only; the database "
                "does not establish complete account or household coverage."
            ),
            "No taxable income rate or total tax estimate is calculated.",
            (
                "The U.S. federal rule scope is documented in the Stage 3 "
                "release notes and source policy."
            ),
        ]
        return {
            "methodology_version": SALE_METHOD_VERSION,
            "jurisdiction_policy_version": US_TAX_POLICY_VERSION,
            "account_id": request.account_id,
            "security_id": request.security_id,
            "sale_date": request.sale_date,
            "target_type": request.target_type,
            "target_amount": request.target_amount,
            "currency": security.currency,
            "baseline": baseline,
            "scenarios": scenario_results,
            "calculation_fingerprint": calculation_fingerprint,
            "canonical_records_mutated": False,
            "persisted": False,
            "disclosures": disclosures,
        }
