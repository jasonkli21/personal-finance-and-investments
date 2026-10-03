"""Read-only portfolio trade, exposure, overlap, and allocation scenarios."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.stage3_contracts import PortfolioScenarioRequest
from app.db.models import (
    Account,
    FundLine,
    FundSnapshot,
    Issuer,
    PositionSnapshot,
    Security,
)
from app.domains import exposure, reports

SCENARIO_VERSION = "portfolio-trade-scenario-v1"
USD_QUANTUM = Decimal("0.0000000001")
PERCENT_QUANTUM = Decimal("0.0000000001")
MAX_VALUE = Decimal("1e18")
EXPOSURE_CATEGORIES = {
    "direct",
    "indirect",
    "cash",
    "opaque_fund",
    "nested_fund",
    "missing_weight",
    "unknown_other",
}


class PortfolioScenarioError(ValueError):
    """A hypothetical portfolio change cannot be calculated safely."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)


def _text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _fund_composition(
    session: Session, inputs: dict[str, Any], security_id: UUID, as_of: datetime
) -> None:
    """Load the same dated published fund evidence used by portfolio reports."""
    key = str(security_id)
    if key in inputs["funds"]:
        return
    snapshots = list(
        session.scalars(
            select(FundSnapshot)
            .where(
                FundSnapshot.fund_security_id == security_id,
                FundSnapshot.status == "published",
                FundSnapshot.as_of <= as_of.date(),
            )
            .order_by(FundSnapshot.as_of.desc())
            .limit(10_001)
        )
    )
    if len(snapshots) > 10_000:
        raise PortfolioScenarioError("Fund history exceeds the safe scenario limit.")
    priorities = os.environ.get("FUND_SOURCE_PRIORITY", "").split(",")

    def rank(source: str) -> int:
        return priorities.index(source) if source in priorities else len(priorities)

    snapshot = (
        min(
            snapshots,
            key=lambda item: (
                -item.as_of.toordinal(),
                rank(item.source),
                -reports.aware(item.published_at).timestamp()
                if item.published_at
                else 0,
                str(item.id),
            ),
        )
        if snapshots
        else None
    )
    if snapshot is None:
        return
    threshold = (
        int(os.environ.get("MANUAL_FUND_STALE_DAYS", "30"))
        if snapshot.parser_version.startswith("manual")
        else int(os.environ.get("ISSUER_FUND_STALE_DAYS", "7"))
    )
    if threshold < 0:
        raise PortfolioScenarioError("Fund freshness days must be nonnegative.")
    security_rows = {str(row.id): row for row in session.scalars(select(Security))}
    issuer_names = {
        str(row.id): row.display_name for row in session.scalars(select(Issuer))
    }

    def security_info(row: Security | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": str(row.id),
            "label": row.display_ticker or row.name,
            "type": row.security_type,
            "issuer_id": str(row.issuer_id) if row.issuer_id else None,
            "issuer_name": issuer_names.get(str(row.issuer_id))
            if row.issuer_id
            else None,
        }

    fund_security = session.get(Security, security_id)
    if fund_security is None:
        raise PortfolioScenarioError("Trade security not found.")
    inputs["funds"][key] = {
        "id": str(snapshot.id),
        "as_of": snapshot.as_of.isoformat(),
        "fetched_at": reports.aware(snapshot.fetched_at).isoformat(),
        "source": snapshot.source,
        "source_url": snapshot.source_url,
        "quality_status": snapshot.quality_status,
        "stale": as_of.date() - snapshot.as_of > timedelta(days=threshold),
        "lines": [
            {
                "id": str(line.id),
                "row_number": line.row_number,
                "weight": str(line.weight),
                "security": security_info(
                    security_rows.get(str(line.security_id))
                    if line.security_id
                    else None
                ),
                "asset_type": line.asset_type,
                "raw_name": line.raw_name,
                "raw_identifier": line.raw_identifier,
            }
            for line in session.scalars(
                select(FundLine)
                .where(FundLine.snapshot_id == snapshot.id)
                .order_by(FundLine.row_number)
            )
        ],
    }


def _overlap(report: dict[str, Any]) -> tuple[list[dict[str, Any]], Decimal]:
    grouped: dict[str, dict[str, Any]] = {}
    for contribution in report["contributions"]:
        if contribution["category"] != "indirect":
            continue
        fund_id = contribution["owned_security_id"]
        security_id = contribution["security_id"]
        amount = Decimal(contribution["amount"])
        if not fund_id or not security_id or amount <= 0:
            continue
        row = grouped.setdefault(
            security_id,
            {
                "security_id": security_id,
                "label": contribution["label"],
                "fund_amounts": {},
                "fund_labels": {},
            },
        )
        row["fund_amounts"][fund_id] = (
            Decimal(row["fund_amounts"].get(fund_id, Decimal(0))) + amount
        )
        row["fund_labels"][fund_id] = contribution["owned_label"]
    overlaps = []
    shared_total = Decimal(0)
    for row in grouped.values():
        amounts: dict[str, Decimal] = row["fund_amounts"]
        if len(amounts) < 2:
            continue
        shared_amount = sum(amounts.values(), Decimal(0))
        shared_total += shared_amount
        fund_ids = sorted(amounts)
        overlaps.append(
            {
                "security_id": row["security_id"],
                "label": row["label"],
                "fund_count": len(fund_ids),
                "fund_ids": fund_ids,
                "fund_labels": [row["fund_labels"][fund_id] for fund_id in fund_ids],
                "fund_amounts": {
                    fund_id: _text(amounts[fund_id]) for fund_id in fund_ids
                },
                "shared_indirect_amount": _text(shared_amount),
            }
        )
    overlaps.sort(
        key=lambda item: (-Decimal(item["shared_indirect_amount"]), item["security_id"])
    )
    return overlaps, shared_total


def _exposure_snapshot(
    report: dict[str, Any], inputs: dict[str, Any], targets: dict[str, Decimal]
) -> dict[str, Any]:
    categories = {key: Decimal(value) for key, value in report["categories"].items()}
    nav = Decimal(report["included_valued_nav"])
    direct = categories.get("direct", Decimal(0))
    indirect = categories.get("indirect", Decimal(0))
    residual_categories = {
        key: value
        for key, value in categories.items()
        if key not in {"direct", "indirect"}
    }
    residual = sum(residual_categories.values(), Decimal(0))
    reconciled = direct + indirect + residual == nav and report["reconciled"]
    if not reconciled:
        raise PortfolioScenarioError(
            "Portfolio scenario decomposition failed to reconcile."
        )
    opaque_unknown = sum(
        (
            categories.get(key, Decimal(0))
            for key in ("opaque_fund", "nested_fund", "missing_weight", "unknown_other")
        ),
        Decimal(0),
    )
    percentages_available = bool(report["percentages_available"])
    if not targets:
        drift_status = "not_requested"
        drift_rows = []
    elif not percentages_available or nav <= 0:
        drift_status = "unavailable"
        drift_rows = [
            {
                "category": category,
                "target_percent": _text(targets.get(category, Decimal(0))),
                "actual_percent": None,
                "drift_percentage_points": None,
            }
            for category in sorted(EXPOSURE_CATEGORIES)
        ]
    else:
        drift_status = "available"
        drift_rows = []
        for category in sorted(EXPOSURE_CATEGORIES):
            target = targets.get(category, Decimal(0))
            actual = (
                categories.get(category, Decimal(0)) / nav * Decimal(100)
            ).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
            delta = (actual - target).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
            drift_rows.append(
                {
                    "category": category,
                    "target_percent": _text(target),
                    "actual_percent": _text(actual),
                    "drift_percentage_points": _text(delta),
                }
            )
    funds = [
        {
            "security_id": key,
            "snapshot_id": record["id"],
            "as_of": record["as_of"],
            "source": record["source"],
            "source_url": record["source_url"],
            "quality_status": record["quality_status"],
            "stale": record["stale"],
        }
        for key, record in sorted(inputs["funds"].items())
    ]
    overlaps, shared_total = _overlap(report)
    return {
        "included_valued_nav": _text(nav),
        "total_portfolio_nav": report["total_portfolio_nav"],
        "nav_status": report["nav_status"],
        "percentages_available": percentages_available,
        "direct_assets": _text(direct),
        "indirect_lookthrough": _text(indirect),
        "residual": _text(residual),
        "residual_categories": {
            key: _text(value) for key, value in sorted(residual_categories.items())
        },
        "opaque_and_unknown_value": _text(opaque_unknown),
        "categories": report["categories"],
        "reconciled": reconciled,
        "security_rows": report["security_rows"],
        "issuer_rows": report["issuer_rows"],
        "overlap_rows": overlaps,
        "shared_indirect_amount": _text(shared_total),
        "drift_status": drift_status,
        "drift_rows": drift_rows,
        "fund_snapshots": funds,
        "warnings": report["warnings"],
    }


def simulate_portfolio(
    session: Session, request: PortfolioScenarioRequest
) -> dict[str, Any]:
    """Calculate before/after portfolio exposures without updating actual rows."""
    as_of = request.as_of.astimezone(UTC)
    if as_of > datetime.now(UTC):
        raise PortfolioScenarioError(
            "Future portfolio valuation times are unsupported."
        )
    if request.financing_policy != "cash_only":
        raise PortfolioScenarioError("Only the explicit cash-only policy is supported.")

    try:
        inputs = reports.capture(
            session,
            request.account_ids,
            as_of,
            False,
            datetime.now(UTC),
        )
    except ValueError as exc:
        raise PortfolioScenarioError(str(exc)) from exc
    selected_ids = [UUID(value) for value in inputs["account_ids"]]
    if not selected_ids:
        raise PortfolioScenarioError("Select at least one active account with history.")
    if request.account_ids and set(request.account_ids) != set(selected_ids):
        raise PortfolioScenarioError("Every selected account must be active.")
    if len(selected_ids) > 500:
        raise PortfolioScenarioError("A scenario is limited to 500 accounts.")
    for line in inputs["owned"]:
        if line["stale"] or line["quality_status"] in {"stale", "estimated"}:
            inputs["warnings"].append(
                f"{line['label']}: valuation price is stale or estimated"
            )
        if line["status"] == "foreign_currency":
            inputs["warnings"].append(
                f"{line['label']}: {line['currency']} value is excluded because no "
                "FX conversion is applied"
            )
        elif line["status"] == "unpriced":
            inputs["warnings"].append(
                f"{line['label']}: value is unavailable because no eligible price "
                "was found"
            )
        elif line["status"] == "unresolved":
            inputs["warnings"].append(
                f"{line['label']}: security is unresolved and excluded from valued NAV"
            )

    selected_accounts = {
        account.id: account
        for account in session.scalars(
            select(Account).where(Account.id.in_(selected_ids)).order_by(Account.id)
        )
    }
    snapshots: dict[UUID, PositionSnapshot] = {}
    for account_id in selected_ids:
        snapshot = session.scalar(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.account_id == account_id,
                PositionSnapshot.status.in_(("accepted", "superseded")),
                PositionSnapshot.snapshot_at <= as_of,
            )
            .order_by(
                PositionSnapshot.snapshot_at.desc(),
                PositionSnapshot.revision.desc(),
            )
            .limit(1)
        )
        if snapshot is None:
            account_name = selected_accounts[account_id].name
            raise PortfolioScenarioError(
                f"{account_name} has no eligible accepted position snapshot."
            )
        snapshots[account_id] = snapshot

    targets: dict[str, Decimal] = {
        item.category: Decimal(item.target_percent) for item in request.category_targets
    }
    before_inputs = json.loads(json.dumps(inputs))
    try:
        before_report = exposure.calculate(before_inputs)
    except ValueError as exc:
        raise PortfolioScenarioError(str(exc)) from exc
    baseline_fingerprint = _digest(
        {
            "exposure_version": exposure.VERSION,
            "as_of": as_of,
            "input_snapshot": before_inputs,
            "snapshot_ids": {str(key): value.id for key, value in snapshots.items()},
        }
    )
    before_snapshot = _exposure_snapshot(before_report, before_inputs, targets)
    after_inputs = json.loads(json.dumps(inputs))

    for trade in request.trades:
        if trade.account_id not in selected_accounts:
            raise PortfolioScenarioError(
                "Each trade account must be included in the baseline."
            )
        security = session.get(Security, trade.security_id)
        if security is None:
            raise PortfolioScenarioError("Trade security not found.")
        if security.security_type not in {"equity", "etf"}:
            raise PortfolioScenarioError(
                "Only actual equity or ETF positions can be traded."
            )
        if security.currency != "USD" or trade.currency != "USD":
            raise PortfolioScenarioError(
                "Portfolio scenarios currently support USD securities only."
            )
        quantity = Decimal(trade.quantity)
        price = Decimal(trade.price)
        fee = Decimal(trade.fee_amount)
        if quantity <= 0 or price <= 0 or fee < 0:
            raise PortfolioScenarioError(
                "Trade quantity and price must be positive; fees cannot be negative."
            )
        if security.security_type == "etf":
            _fund_composition(session, after_inputs, security.id, as_of)

    position_index: dict[tuple[str, str], dict[str, Any]] = {}
    for line in after_inputs["owned"]:
        if line["security_id"]:
            position_index[(line["account_id"], line["security_id"])] = line

    cash_before: dict[UUID, Decimal] = defaultdict(Decimal)
    for line in inputs["owned"]:
        if (
            line["security_type"] == "cash"
            and line["currency"] == "USD"
            and line["status"] == "valued"
        ):
            cash_before[UUID(line["account_id"])] += Decimal(line["value"])
    cash_assumptions: dict[UUID, Decimal] = defaultdict(Decimal)
    cash_trade_deltas: dict[UUID, Decimal] = defaultdict(Decimal)
    for cash_input in request.cash_changes:
        if cash_input.account_id not in selected_accounts:
            raise PortfolioScenarioError(
                "Each cash assumption account must be included in the baseline."
            )
        if cash_input.currency != "USD":
            raise PortfolioScenarioError(
                "Portfolio cash assumptions currently support USD only."
            )
        cash_assumptions[cash_input.account_id] += Decimal(cash_input.amount)

    trade_results: list[dict[str, Any]] = []
    for trade in request.trades:
        account_id = trade.account_id
        account_key = str(account_id)
        security_id = str(trade.security_id)
        security = session.get(Security, trade.security_id)
        assert security is not None
        quantity = Decimal(trade.quantity)
        execution_price = Decimal(trade.price)
        fee = Decimal(trade.fee_amount)
        existing = position_index.get((account_key, security_id))
        if existing is None:
            if trade.side == "sell":
                raise PortfolioScenarioError(
                    "A sale must come from an actually owned position."
                )
            quantity_before = Decimal(0)
            unit_value_price = execution_price
            value_before = Decimal(0)
            price_source = "user_trade_price_assumption"
            security_info = {
                "id": security_id,
                "label": security.display_ticker or security.name,
                "type": security.security_type,
                "issuer_id": str(security.issuer_id) if security.issuer_id else None,
                "issuer_name": None,
            }
            if security.issuer_id:
                issuer = session.get(Issuer, security.issuer_id)
                security_info["issuer_name"] = issuer.display_name if issuer else None
            existing = {
                "account_id": account_key,
                "account_name": selected_accounts[account_id].name,
                "position_id": f"scenario-position:{account_id}:{security_id}",
                "position_snapshot_id": str(snapshots[account_id].id),
                "position_revision": snapshots[account_id].revision,
                "position_as_of": as_of.isoformat(),
                "position_source": "user_trade_assumption",
                "position_quality": "scenario_assumption",
                "security_id": security_id,
                "security_type": security.security_type,
                "security": security_info,
                "label": security.display_ticker or security.name,
                "quantity": "0",
                "price": _text(unit_value_price),
                "value": "0",
                "currency": "USD",
                "status": "valued",
                "quote_id": None,
                "quote_as_of": as_of.isoformat(),
                "quote_source": price_source,
                "quality_status": "scenario_assumption",
                "stale": False,
            }
            position_index[(account_key, security_id)] = existing
            after_inputs["owned"].append(existing)
        else:
            if existing["status"] != "valued" or existing["price"] is None:
                raise PortfolioScenarioError(
                    f"{security.display_ticker or security.name} has no complete "
                    "USD baseline valuation."
                )
            quantity_before = Decimal(existing["quantity"])
            unit_value_price = Decimal(existing["price"])
            value_before = Decimal(existing["value"])
            price_source = existing["quote_source"] or existing["position_source"]
            if quantity_before < 0:
                raise PortfolioScenarioError(
                    "Short baseline holdings are not supported by cash-only scenarios."
                )

        gross = _money(quantity * execution_price)
        if gross <= 0:
            raise PortfolioScenarioError(
                "Trade amount rounds to zero at 10 decimal places."
            )
        if trade.side == "sell" and fee > gross:
            raise PortfolioScenarioError("Sale fees cannot exceed gross sale proceeds.")
        quantity_after = (
            quantity_before + quantity
            if trade.side == "buy"
            else quantity_before - quantity
        )
        if quantity_after < 0:
            raise PortfolioScenarioError(
                "Sale quantity exceeds the actual owned position."
            )
        value_after = quantity_after * unit_value_price
        if abs(value_after) >= MAX_VALUE or gross >= MAX_VALUE:
            raise PortfolioScenarioError(
                "Trade value exceeds NUMERIC(28, 10) precision."
            )
        cash_delta = -(gross + fee) if trade.side == "buy" else gross - fee
        cash_trade_deltas[account_id] += cash_delta
        existing["quantity"] = _text(quantity_after)
        existing["price"] = _text(unit_value_price)
        existing["value"] = _text(value_after)
        existing["status"] = "valued"
        trade_results.append(
            {
                "account_id": account_id,
                "account_name": selected_accounts[account_id].name,
                "security_id": security.id,
                "ticker": security.display_ticker,
                "side": trade.side,
                "quantity": trade.quantity,
                "quantity_before": _text(quantity_before),
                "quantity_after": _text(quantity_after),
                "execution_price": trade.price,
                "currency": "USD",
                "gross_amount": _text(gross),
                "fee_amount": _text(fee),
                "cash_delta": _text(cash_delta),
                "market_value_before": _text(value_before),
                "market_value_after": _text(value_after),
                "valuation_price_source": price_source,
            }
        )

    changed_accounts = set(cash_assumptions) | set(cash_trade_deltas)
    cash_after: dict[UUID, Decimal] = {}
    for account_id in selected_ids:
        result = (
            cash_before[account_id]
            + cash_assumptions[account_id]
            + cash_trade_deltas[account_id]
        )
        if account_id in changed_accounts and result < 0:
            raise PortfolioScenarioError(
                f"{selected_accounts[account_id].name} would exceed available "
                "cash under the cash-only policy."
            )
        if abs(result) >= MAX_VALUE:
            raise PortfolioScenarioError(
                "Scenario cash exceeds NUMERIC(28, 10) precision."
            )
        cash_after[account_id] = result

    # Consolidate USD cash lines into one derived per-account cash position.
    # Foreign-currency cash stays present as an explicit incomplete amount.
    non_usd_cash_and_non_cash = [
        line
        for line in after_inputs["owned"]
        if not (
            line["security_type"] == "cash"
            and line["currency"] == "USD"
            and line["status"] == "valued"
        )
    ]
    after_inputs["owned"] = non_usd_cash_and_non_cash
    affected_cash_accounts = {
        UUID(line["account_id"])
        for line in inputs["owned"]
        if line["security_type"] == "cash"
        and line["currency"] == "USD"
        and line["status"] == "valued"
    } | changed_accounts
    for account_id in sorted(affected_cash_accounts, key=str):
        snapshot = snapshots[account_id]
        after_inputs["owned"].append(
            {
                "account_id": str(account_id),
                "account_name": selected_accounts[account_id].name,
                "position_id": f"scenario-cash:{account_id}",
                "position_snapshot_id": str(snapshot.id),
                "position_revision": snapshot.revision,
                "position_as_of": as_of.isoformat(),
                "position_source": "scenario_cash_assumption",
                "position_quality": "scenario_assumption",
                "security_id": f"scenario-cash:{account_id}",
                "security_type": "cash",
                "security": None,
                "label": "Hypothetical USD cash",
                "quantity": _text(cash_after[account_id]),
                "price": None,
                "value": _text(cash_after[account_id]),
                "currency": "USD",
                "status": "valued",
                "quote_id": None,
                "quote_as_of": as_of.isoformat(),
                "quote_source": "scenario_cash_assumption",
                "quality_status": "scenario_assumption",
                "stale": False,
            }
        )

    after_report = exposure.calculate(after_inputs)
    after_snapshot = _exposure_snapshot(after_report, after_inputs, targets)
    cash_change_results = [
        {
            "account_id": item.account_id,
            "account_name": selected_accounts[item.account_id].name,
            "amount": item.amount,
            "currency": "USD",
            "label": item.label,
        }
        for item in request.cash_changes
    ]
    cash_results = [
        {
            "account_id": account_id,
            "account_name": selected_accounts[account_id].name,
            "currency": "USD",
            "cash_before": _text(cash_before[account_id]),
            "assumption_delta": _text(cash_assumptions[account_id]),
            "trade_delta": _text(cash_trade_deltas[account_id]),
            "cash_after": _text(cash_after[account_id]),
        }
        for account_id in sorted(selected_ids, key=str)
    ]
    scenario_fingerprint = _digest(
        {
            "version": SCENARIO_VERSION,
            "baseline_fingerprint": baseline_fingerprint,
            "request": request.model_dump(mode="json"),
            "after_categories": after_report["categories"],
            "after_fund_ids": {
                key: value["id"] for key, value in after_inputs["funds"].items()
            },
        }
    )
    assumptions = [
        (
            "The result is a read-only hypothetical calculation; no position, "
            "transaction, lot, or cash record is changed or saved."
        ),
        (
            "Only USD equity, ETF, and cash values are included in valued NAV; "
            "foreign-currency or unpriced positions make NAV incomplete."
        ),
        (
            "Trade prices are execution assumptions. Existing holdings are "
            "valued at the frozen baseline price; new positions use the entered "
            "trade price until another source-backed valuation exists. Any "
            "difference between an existing holding's execution price and its "
            "frozen valuation price changes the scenario's valued NAV."
        ),
        (
            "Cash-only financing is required. Each trade's settlement and "
            "explicit cash changes must leave its account at nonnegative USD cash."
        ),
        (
            "ETF look-through uses the same one-level exposure engine and the "
            "latest published fund snapshot on or before the valuation date. "
            "Missing or opaque portions remain residual and are never added to "
            "net worth."
        ),
        (
            "Overlap reports shared membership by exact security IDs and the "
            "resulting dollar exposure across held funds; it is descriptive and "
            "does not add exposure to NAV."
        ),
        (
            "Category targets are user-entered comparisons only. Unlisted "
            "categories have a zero target; no allocation or rebalance is "
            "recommended."
        ),
        (
            "Transaction gross amounts, fees, and cash settlement are rounded "
            "half-up to 10 decimal places; market values remain at the source "
            "precision used by the exposure engine."
        ),
    ]
    return {
        "methodology_version": SCENARIO_VERSION,
        "exposure_calculation_version": exposure.VERSION,
        "as_of": as_of,
        "account_ids": selected_ids,
        "account_names": [
            selected_accounts[account_id].name for account_id in selected_ids
        ],
        "account_position_revisions": {
            str(account_id): snapshot.revision
            for account_id, snapshot in sorted(
                snapshots.items(), key=lambda row: str(row[0])
            )
        },
        "position_snapshot_ids": {
            str(account_id): snapshot.id
            for account_id, snapshot in sorted(
                snapshots.items(), key=lambda row: str(row[0])
            )
        },
        "financing_policy": request.financing_policy,
        "currency": "USD",
        "before": before_snapshot,
        "after": after_snapshot,
        "trades": trade_results,
        "cash": cash_results,
        "cash_changes": cash_change_results,
        "baseline_fingerprint": baseline_fingerprint,
        "scenario_fingerprint": scenario_fingerprint,
        "canonical_records_mutated": False,
        "persisted": False,
        "assumptions": assumptions,
    }
