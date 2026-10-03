"""Source-backed investment history, reconciliation and return read models."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.stage3_contracts import InvestmentEventCreate
from app.db.models import (
    Account,
    InvestmentEvent,
    PositionSnapshot,
    PositionSnapshotLine,
    Security,
)
from app.domains import performance, portfolio

EVENT_TYPES = {
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
}
RETURN_QUANTUM = Decimal("0.000000000001")
EXTERNAL_EVENT_TYPES = {"deposit", "withdrawal"}


def _return_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rounded = value.quantize(RETURN_QUANTUM, rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = Decimal(0).quantize(RETURN_QUANTUM)
    return format(rounded, "f")


class HistoryError(ValueError):
    """A requested history action cannot be safely applied."""


def create_investment_event(
    session: Session, data: InvestmentEventCreate
) -> InvestmentEvent:
    quantity_delta = (
        Decimal(data.quantity_delta) if data.quantity_delta is not None else None
    )
    cash_amount = Decimal(data.cash_amount) if data.cash_amount is not None else None
    account = session.get(Account, data.account_id)
    if account is None or not account.active:
        raise HistoryError("Active account not found.")
    security = session.get(Security, data.security_id) if data.security_id else None
    if data.security_id is not None and security is None:
        raise HistoryError("Security not found.")
    if security is not None and security.currency != data.currency:
        raise HistoryError("Event currency must match the selected security.")
    if data.effective_date > date.today():
        raise HistoryError("Investment events cannot be dated in the future.")
    if data.event_type in {"buy", "sell", "split", "adjustment"} and security is None:
        raise HistoryError("Select an actual owned security for this event type.")
    if (
        data.event_type in EXTERNAL_EVENT_TYPES
        and security is not None
        and security.security_type != "cash"
    ):
        raise HistoryError("External flows may only link to a cash position.")
    if data.event_type == "deposit" and (cash_amount is None or cash_amount <= 0):
        raise HistoryError("A deposit must have a positive cash amount.")
    if data.event_type == "withdrawal" and (cash_amount is None or cash_amount >= 0):
        raise HistoryError("A withdrawal must have a negative cash amount.")
    if data.event_type == "buy" and (quantity_delta is None or quantity_delta <= 0):
        raise HistoryError("A purchase must have a positive quantity change.")
    if data.event_type == "sell" and (quantity_delta is None or quantity_delta >= 0):
        raise HistoryError("A sale must have a negative quantity change.")
    if data.event_type == "transfer_in" and (
        quantity_delta is None or quantity_delta <= 0
    ):
        raise HistoryError("A transfer in must have a positive quantity change.")
    if data.event_type == "transfer_out" and (
        quantity_delta is None or quantity_delta >= 0
    ):
        raise HistoryError("A transfer out must have a negative quantity change.")
    if (
        data.event_type == "transfer_in"
        and cash_amount is not None
        and cash_amount <= 0
    ):
        raise HistoryError("A transfer in cash value must be positive.")
    if (
        data.event_type == "transfer_out"
        and cash_amount is not None
        and cash_amount >= 0
    ):
        raise HistoryError("A transfer out cash value must be negative.")
    if data.event_type in {"split", "adjustment"} and (
        quantity_delta is None or quantity_delta == 0
    ):
        raise HistoryError("A split or adjustment must have a nonzero quantity change.")
    if data.event_type == "dividend" and cash_amount is not None and cash_amount < 0:
        raise HistoryError("A dividend cash amount must be nonnegative.")
    if data.event_type == "fee" and cash_amount is not None and cash_amount > 0:
        raise HistoryError("A fee cash amount must be nonpositive.")
    if data.event_type == "buy" and cash_amount is not None and cash_amount > 0:
        raise HistoryError("A purchase cash change must be nonpositive.")
    if data.event_type == "sell" and cash_amount is not None and cash_amount < 0:
        raise HistoryError("A sale cash change must be nonnegative.")
    if (
        data.event_type in EXTERNAL_EVENT_TYPES
        and security is not None
        and quantity_delta != cash_amount
    ):
        raise HistoryError("Linked cash quantity change must equal the cash amount.")

    is_external_flow = data.event_type in EXTERNAL_EVENT_TYPES
    prior = session.scalar(
        select(InvestmentEvent).where(
            InvestmentEvent.idempotency_key == data.idempotency_key
        )
    )
    if prior is not None:
        same = (
            prior.account_id == data.account_id
            and prior.security_id == data.security_id
            and prior.event_type == data.event_type
            and prior.effective_date == data.effective_date
            and prior.quantity_delta == quantity_delta
        )
        same = same and prior.cash_amount == cash_amount
        same = same and prior.currency == data.currency
        same = same and prior.source_label == data.source_label
        same = same and prior.source_event_id == data.source_event_id
        same = same and prior.evidence_ref == data.evidence_ref
        same = same and prior.raw_values == data.raw_values
        same = same and prior.quality_status == data.quality_status
        if not same:
            raise HistoryError("Idempotency key was used for a different event.")
        return prior

    row = InvestmentEvent(
        id=uuid4(),
        account_id=data.account_id,
        security_id=data.security_id,
        event_type=data.event_type,
        effective_date=data.effective_date,
        quantity_delta=quantity_delta,
        cash_amount=cash_amount,
        currency=data.currency,
        is_external_flow=is_external_flow,
        source_label=data.source_label,
        source_event_id=data.source_event_id,
        evidence_ref=data.evidence_ref,
        quality_status=data.quality_status,
        review_status=(
            "reviewed"
            if data.quality_status in {"reported", "manual"}
            else "needs_review"
        ),
        idempotency_key=data.idempotency_key,
        raw_values=data.raw_values,
    )
    session.add(row)
    session.flush()
    return row


def list_investment_events(
    session: Session,
    *,
    account_id: UUID,
    start_date: date,
    end_date: date,
) -> list[InvestmentEvent]:
    if start_date > end_date:
        raise HistoryError("Start date must not follow end date.")
    account = session.get(Account, account_id)
    if account is None:
        raise HistoryError("Account not found.")
    rows = list(
        session.scalars(
            select(InvestmentEvent)
            .where(
                InvestmentEvent.account_id == account_id,
                InvestmentEvent.effective_date >= start_date,
                InvestmentEvent.effective_date <= end_date,
            )
            .order_by(
                InvestmentEvent.effective_date,
                InvestmentEvent.created_at,
                InvestmentEvent.id,
            )
            .limit(1001)
        )
    )
    if len(rows) > 1000:
        raise HistoryError("Narrow the date range; at most 1,000 events are read.")
    return rows


def _selected_snapshots(
    session: Session, account_id: UUID, start_date: date, end_date: date
) -> list[PositionSnapshot]:
    start_at = datetime.combine(start_date, time.min, tzinfo=UTC)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    snapshots = list(
        session.scalars(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.account_id == account_id,
                PositionSnapshot.snapshot_at >= start_at,
                PositionSnapshot.snapshot_at < end_at,
                PositionSnapshot.status.in_(("accepted", "superseded")),
            )
            .order_by(
                PositionSnapshot.snapshot_at,
                PositionSnapshot.revision,
                PositionSnapshot.id,
            )
            .limit(1001)
        )
    )
    if len(snapshots) > 1000:
        raise HistoryError("Narrow the date range; at most 1,000 snapshots are read.")
    by_date: dict[date, PositionSnapshot] = {}
    for snapshot in snapshots:
        current = by_date.get(snapshot.snapshot_at.date())
        if current is None or (snapshot.revision, snapshot.id) > (
            current.revision,
            current.id,
        ):
            by_date[snapshot.snapshot_at.date()] = snapshot
    return [by_date[key] for key in sorted(by_date)]


def read_history(
    session: Session,
    *,
    account_id: UUID,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    snapshots = _selected_snapshots(session, account_id, start_date, end_date)
    events = list_investment_events(
        session,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
    )
    snapshot_rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        line_count = session.scalar(
            select(func.count(PositionSnapshotLine.id)).where(
                PositionSnapshotLine.snapshot_id == snapshot.id
            )
        )
        snapshot_rows.append(
            {
                "id": snapshot.id,
                "effective_date": snapshot.snapshot_at.date(),
                "revision": snapshot.revision,
                "source": snapshot.source,
                "status": snapshot.status,
                "accepted_at": snapshot.accepted_at,
                "line_count": int(line_count or 0),
            }
        )
    return {
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "snapshots": snapshot_rows,
        "events": [
            {
                "id": event.id,
                "account_id": event.account_id,
                "security_id": event.security_id,
                "event_type": event.event_type,
                "effective_date": event.effective_date,
                "quantity_delta": (
                    str(event.quantity_delta)
                    if event.quantity_delta is not None
                    else None
                ),
                "cash_amount": (
                    str(event.cash_amount) if event.cash_amount is not None else None
                ),
                "currency": event.currency,
                "is_external_flow": event.is_external_flow,
                "source_label": event.source_label,
                "source_event_id": event.source_event_id,
                "evidence_ref": event.evidence_ref,
                "quality_status": event.quality_status,
                "review_status": event.review_status,
                "idempotency_key": event.idempotency_key,
                "created_at": event.created_at,
            }
            for event in events
        ],
        "methodology": (
            "Accepted dated position revisions and explicit source-backed events. "
            "Snapshot differences are not converted into transactions."
        ),
    }


def _performance_dates(
    session: Session, account_id: UUID, start_date: date, end_date: date
) -> list[PositionSnapshot]:
    return _selected_snapshots(session, account_id, start_date, end_date)


def read_performance(
    session: Session,
    *,
    account_id: UUID,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    if start_date >= end_date:
        raise HistoryError("Performance end date must follow start date.")
    account = session.get(Account, account_id)
    if account is None:
        raise HistoryError("Account not found.")
    if account.base_currency != "USD":
        return _unavailable_performance(
            account_id,
            start_date,
            end_date,
            "This calculation currently supports USD account valuations only.",
        )
    snapshots = _performance_dates(session, account_id, start_date, end_date)
    dates = [row.snapshot_at.date() for row in snapshots]
    if not dates or dates[0] != start_date or dates[-1] != end_date:
        return _unavailable_performance(
            account_id,
            start_date,
            end_date,
            "Accepted position valuations are required on both period boundaries.",
            observed_dates=dates,
        )
    points: list[performance.ValuationPoint] = []
    for snapshot in snapshots:
        valuation = portfolio.read_owned_valuation(
            session, account_id, snapshot.snapshot_at.date()
        )
        if valuation["total_usd"] is None or valuation["completeness"] != "complete":
            return _unavailable_performance(
                account_id,
                start_date,
                end_date,
                "A selected valuation is incomplete, stale, or unpriced.",
                observed_dates=dates,
            )
        points.append(
            performance.ValuationPoint(
                snapshot.snapshot_at.date(), Decimal(str(valuation["total_usd"]))
            )
        )
    event_rows = list_investment_events(
        session,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
    )
    unreviewed = [row for row in event_rows if row.review_status != "reviewed"]
    if unreviewed:
        return _unavailable_performance(
            account_id,
            start_date,
            end_date,
            "Unreviewed investment events prevent a return calculation.",
            observed_dates=dates,
        )
    unsupported = [row for row in event_rows if row.event_type == "other"]
    if unsupported:
        return _unavailable_performance(
            account_id,
            start_date,
            end_date,
            "Unsupported investment events prevent a complete return calculation.",
            observed_dates=dates,
        )
    external_rows = [
        row for row in event_rows if row.event_type in EXTERNAL_EVENT_TYPES
    ]
    transfer_rows = [
        row for row in event_rows if row.event_type in {"transfer_in", "transfer_out"}
    ]
    transfer_values: dict[UUID, Decimal] = {}
    for row in transfer_rows:
        amount = row.cash_amount
        if amount is None and row.security_id is not None:
            transfer_security = session.get(Security, row.security_id)
            if (
                transfer_security is not None
                and transfer_security.security_type == "cash"
                and transfer_security.currency == "USD"
            ):
                amount = row.quantity_delta
        if row.currency == "USD" and amount is not None:
            transfer_values[row.id] = amount
    if any(
        row.currency != "USD" or row.cash_amount is None for row in external_rows
    ) or len(transfer_values) != len(transfer_rows):
        return _unavailable_performance(
            account_id,
            start_date,
            end_date,
            "External flows and account transfers need dated USD cash values "
            "before per-account returns can be calculated.",
            observed_dates=dates,
        )
    flows = [
        performance.ExternalFlow(row.effective_date, row.cash_amount or Decimal(0))
        for row in external_rows
    ]
    flows.extend(
        performance.ExternalFlow(row.effective_date, transfer_values[row.id])
        for row in transfer_rows
    )
    twr = performance.chained_modified_dietz(points, flows)
    mwr, mwr_status = performance.money_weighted_return(
        points[0].value, points[-1].value, flows, start_date, end_date
    )
    return {
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "available" if twr is not None else "unavailable",
        "currency": "USD",
        "beginning_value": str(points[0].value),
        "ending_value": str(points[-1].value),
        "time_weighted_return": _return_text(twr),
        "time_weighted_method": "modified_dietz_chained",
        "money_weighted_return": _return_text(mwr),
        "money_weighted_status": mwr_status,
        "methodology_version": performance.PERFORMANCE_VERSION,
        "observation_count": len(points),
        "external_flow_count": len(external_rows),
        "observed_dates": dates,
        "diagnostics": [
            "Returns use accepted, complete USD position snapshots only.",
            "Modified Dietz chains observed subperiods and weights external flows "
            "by calendar days; this is an estimate, not exact daily time-weighted "
            "return.",
            "Money-weighted return is annualized XIRR, solved only when the dated "
            "cash flows indicate a single root in the bounded -99.99% to 1,000% "
            "range. Both rates are return fractions rounded half-up to 12 decimal "
            "places.",
            "Snapshot appreciation is not used to invent acquisition history or "
            "cash flows.",
        ],
    }


def _unavailable_performance(
    account_id: UUID,
    start_date: date,
    end_date: date,
    reason: str,
    *,
    observed_dates: list[date] | None = None,
) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "unavailable",
        "currency": "USD",
        "beginning_value": None,
        "ending_value": None,
        "time_weighted_return": None,
        "time_weighted_method": "modified_dietz_chained",
        "money_weighted_return": None,
        "money_weighted_status": "unavailable",
        "methodology_version": performance.PERFORMANCE_VERSION,
        "observation_count": len(observed_dates or []),
        "external_flow_count": 0,
        "observed_dates": observed_dates or [],
        "diagnostics": [reason],
    }


def reconcile_history(
    session: Session,
    *,
    account_id: UUID,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    if start_date >= end_date:
        raise HistoryError("Reconciliation end date must follow start date.")
    account = session.get(Account, account_id)
    if account is None:
        raise HistoryError("Account not found.")
    start_positions = portfolio.read_positions(session, account_id, start_date)
    end_positions = portfolio.read_positions(session, account_id, end_date)
    if (
        start_positions.snapshot is None
        or end_positions.snapshot is None
        or start_positions.snapshot.effective_date != start_date
        or end_positions.snapshot.effective_date != end_date
    ):
        return {
            "status": "unavailable",
            "account_id": account_id,
            "start_date": start_date,
            "end_date": end_date,
            "differences": [],
            "gaps": ["Accepted position snapshots are required at both dates."],
        }
    quantities: dict[UUID, Decimal] = {}
    start_cash: dict[str, list[UUID]] = {}
    for position in start_positions.snapshot.positions:
        quantities[position.security.id] = Decimal(position.quantity)
        security = position.security
        if security.security_type == "cash":
            start_cash.setdefault(position.currency, []).append(security.id)
    events = list_investment_events(
        session,
        account_id=account_id,
        start_date=start_date + timedelta(days=1),
        end_date=end_date,
    )
    gaps: list[str] = []
    for event in events:
        if event.review_status != "reviewed":
            gaps.append(f"Event {event.id} has not been reviewed.")
            continue
        if event.event_type in EXTERNAL_EVENT_TYPES and event.security_id is None:
            gaps.append(
                f"External flow {event.id} is not linked to a cash position; "
                "cash reconciliation is unavailable for that event."
            )
        if event.event_type in {
            "buy",
            "sell",
            "deposit",
            "withdrawal",
            "transfer_in",
            "transfer_out",
            "split",
        }:
            if event.security_id is None or event.quantity_delta is None:
                gaps.append(
                    f"{event.event_type} event {event.id} lacks a security or quantity."
                )
                continue
            quantities[event.security_id] = (
                quantities.get(event.security_id, Decimal(0)) + event.quantity_delta
            )
        elif event.event_type == "adjustment":
            if event.security_id is not None and event.quantity_delta is not None:
                quantities[event.security_id] = (
                    quantities.get(event.security_id, Decimal(0)) + event.quantity_delta
                )
            else:
                gaps.append(
                    f"Adjustment event {event.id} lacks a security or quantity."
                )
        elif event.event_type in {"dividend", "fee"}:
            pass
        elif event.event_type == "other":
            gaps.append(
                f"Event {event.id} may affect quantities but is not applied "
                "automatically."
            )
        else:
            gaps.append(
                f"Event {event.id} ({event.event_type}) has unsupported quantity "
                "effects."
            )
        if event.event_type in {"buy", "sell", "dividend", "fee"}:
            cash_ids = start_cash.get(event.currency, [])
            if event.cash_amount is None:
                gaps.append(
                    f"{event.event_type.title()} event {event.id} has no cash amount; "
                    "cash reconciliation is unavailable."
                )
            elif len(cash_ids) != 1:
                gaps.append(
                    f"{event.event_type.title()} event {event.id} cannot be matched "
                    "to one actual currency cash security."
                )
            else:
                cash_id = cash_ids[0]
                quantities[cash_id] = (
                    quantities.get(cash_id, Decimal(0)) + event.cash_amount
                )
    expected = quantities
    actual: dict[UUID, Decimal] = {}
    for position in end_positions.snapshot.positions:
        actual[position.security.id] = Decimal(position.quantity)
    differences = []
    for security_id in sorted(set(expected) | set(actual), key=str):
        catalog_security = session.get(Security, security_id)
        expected_quantity = expected.get(security_id, Decimal(0))
        actual_quantity = actual.get(security_id, Decimal(0))
        differences.append(
            {
                "security_id": security_id,
                "ticker": catalog_security.display_ticker if catalog_security else None,
                "expected_quantity": str(expected_quantity),
                "snapshot_quantity": str(actual_quantity),
                "difference": str(actual_quantity - expected_quantity),
            }
        )
    matched = all(
        actual.get(security_id, Decimal(0)) == expected.get(security_id, Decimal(0))
        for security_id in set(expected) | set(actual)
    )
    return {
        "status": "matched" if matched and not gaps else "discrepancy",
        "account_id": account_id,
        "start_date": start_date,
        "end_date": end_date,
        "differences": differences,
        "gaps": gaps,
        "methodology": (
            "Starting quantities plus explicit reviewed security quantity deltas "
            "are compared with the ending accepted snapshot. No balancing events "
            "are inferred or inserted."
        ),
    }
