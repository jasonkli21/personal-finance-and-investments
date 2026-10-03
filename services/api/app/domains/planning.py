"""Bounded, read-only liquidity and large-purchase planning calculations."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.stage3_contracts import PlanningScenarioRequest
from app.db.models import (
    Account,
    AccountBalanceObservation,
    ActiveTransferTransaction,
    FinancialTransaction,
    InvestmentEvent,
)
from app.domains import portfolio

METHODOLOGY_VERSION = "liquidity-planning-v1"
MONEY_QUANTUM = Decimal("0.0000000001")
MAX_VALUE = Decimal("1e18")
RETIREMENT_ACCOUNT_TYPES = {"ira", "roth_ira", "401k", "hsa"}
CASH_ACCOUNT_TYPES = {"cash", "checking", "savings", "bank"}
LIABILITY_ONLY_ACCOUNT_TYPES = {
    "credit_card",
    "credit-card",
    "loan",
    "mortgage",
    "liability",
}
SPENDING_CLASSES = {"expense", "refund", "fee"}
EXCLUDED_CLASSES = {"transfer", "card_payment"}


class PlanningError(ValueError):
    """Planning inputs or available source evidence are not usable."""


def _round(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _next_month(month: date, months: int = 1) -> date:
    ordinal = month.year * 12 + month.month - 1 + months
    return date(ordinal // 12, ordinal % 12 + 1, 1)


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _currency_bucket() -> dict[str, Decimal]:
    return {
        "liquid_cash": Decimal(0),
        "investment_assets": Decimal(0),
        "restricted_assets": Decimal(0),
        "other_assets": Decimal(0),
        "liabilities": Decimal(0),
    }


def _baseline_calculate(
    session: Session, accounts: list[Account], as_of: date
) -> dict[str, Any]:
    account_ids = [account.id for account in accounts]
    latest_balances: dict[UUID, AccountBalanceObservation] = {}
    for account_id in account_ids:
        observation = session.scalar(
            select(AccountBalanceObservation)
            .where(
                AccountBalanceObservation.account_id == account_id,
                AccountBalanceObservation.as_of <= as_of,
            )
            .order_by(
                AccountBalanceObservation.as_of.desc(),
                AccountBalanceObservation.revision.desc(),
            )
            .limit(1)
        )
        if observation is not None:
            latest_balances[account_id] = observation

    rows: list[dict[str, Any]] = []
    totals: dict[str, dict[str, Decimal]] = defaultdict(_currency_bucket)
    bucket_aliases = {
        "investment": "investment_assets",
        "restricted_asset": "restricted_assets",
        "other_asset": "other_assets",
        "foreign_asset": "other_assets",
        "liability": "liabilities",
    }
    per_currency_incomplete: dict[str, bool] = defaultdict(bool)
    warnings: list[str] = []
    balance_sheet_complete = True
    cash_coverage_complete = True
    liquid_cash_usd = Decimal(0)
    position_snapshot_ids: dict[str, UUID] = {}
    position_revisions: dict[str, int] = {}
    account_balance_ids: dict[str, UUID] = {}
    balance_revisions: dict[str, int] = {}

    def add_balance(
        *,
        account: Account,
        effective_date: date | None,
        price_as_of: datetime | None = None,
        currency: str | None,
        amount: Decimal | None,
        bucket: str,
        source: str | None,
        quality: str,
        status: str,
        detail: str | None,
        included_in_starting_cash: bool = False,
        position_snapshot_id: UUID | None = None,
        position_revision: int | None = None,
        account_balance_id: UUID | None = None,
        balance_revision: int | None = None,
    ) -> None:
        nonlocal balance_sheet_complete, cash_coverage_complete, liquid_cash_usd
        rows.append(
            {
                "account_id": account.id,
                "account_name": account.name,
                "account_type": account.account_type,
                "position_snapshot_id": position_snapshot_id,
                "position_revision": position_revision,
                "account_balance_id": account_balance_id,
                "balance_revision": balance_revision,
                "as_of": effective_date,
                "price_as_of": price_as_of,
                "currency": currency,
                "amount": _text(amount),
                "bucket": bucket,
                "source": source,
                "quality_status": quality,
                "status": status,
                "detail": detail,
                "included_in_starting_cash": included_in_starting_cash,
            }
        )
        if currency is not None:
            if amount is not None:
                aggregate_bucket = bucket_aliases.get(bucket, bucket)
                if aggregate_bucket in totals[currency]:
                    totals[currency][aggregate_bucket] += amount
                if included_in_starting_cash:
                    liquid_cash_usd += amount
            if status in {"stale", "estimated", "unpriced", "unavailable"}:
                per_currency_incomplete[currency] = True
                if included_in_starting_cash:
                    cash_coverage_complete = False
        if status in {"stale", "estimated", "unpriced", "unavailable"}:
            balance_sheet_complete = False

    position_line_count = 0
    for account in accounts:
        kind = account.account_type.casefold().replace(" ", "_")
        is_retirement = kind in RETIREMENT_ACCOUNT_TYPES
        is_cash_account = kind in CASH_ACCOUNT_TYPES
        is_liability_only = kind in LIABILITY_ONLY_ACCOUNT_TYPES
        envelope = portfolio.read_positions(session, account.id, as_of)
        if envelope.snapshot is not None:
            position_line_count += len(envelope.snapshot.positions)
            if position_line_count > 10000:
                raise PlanningError(
                    "Planning exceeds 10,000 position lines; select fewer accounts."
                )
            position_snapshot_ids[str(account.id)] = envelope.snapshot.id
            position_revisions[str(account.id)] = envelope.snapshot.revision
            valuation = portfolio.read_owned_valuation(session, account.id, as_of)
            valuation_lines = cast(list[dict[str, Any]], valuation["lines"])
            values_by_line = {
                str(line["position_id"]): line for line in valuation_lines
            }
            usd_cash_seen = False
            for position in envelope.snapshot.positions:
                valued = values_by_line.get(str(position.id), {})
                currency = str(valued.get("value_currency") or position.currency)
                status = str(valued.get("status") or "unpriced")
                quality = str(valued.get("quality_status") or position.quality_status)
                source = str(valued.get("price_source") or position.source)
                value = (
                    Decimal(str(valued["value"]))
                    if valued.get("value") is not None
                    else None
                )
                security_type = position.security.security_type
                if status == "foreign_currency":
                    warnings.append(
                        f"{account.name}: {position.security.name} is held in "
                        f"{currency}; no FX conversion is applied."
                    )
                bucket = (
                    "restricted_asset"
                    if is_retirement
                    else "liquid_cash"
                    if security_type == "cash"
                    else "investment"
                )
                included_in_cash = (
                    security_type == "cash"
                    and currency == "USD"
                    and status == "valued"
                    and not is_retirement
                )
                if security_type == "cash" and currency == "USD":
                    usd_cash_seen = True
                if security_type != "cash" and value is None:
                    bucket = "unavailable"
                line_status = (
                    "stale"
                    if quality == "stale"
                    else "estimated"
                    if quality in {"estimated", "inferred", "unreviewed"}
                    else "unpriced"
                    if value is None
                    else "foreign_currency"
                    if currency != "USD"
                    else "valued"
                )
                add_balance(
                    account=account,
                    effective_date=envelope.snapshot.effective_date,
                    price_as_of=cast(datetime | None, valued.get("price_as_of")),
                    currency=currency,
                    amount=value,
                    bucket=bucket,
                    source=source,
                    quality=quality,
                    status=line_status,
                    detail=position.security.display_ticker or position.security.name,
                    included_in_starting_cash=included_in_cash,
                    position_snapshot_id=envelope.snapshot.id,
                    position_revision=envelope.snapshot.revision,
                )
                if line_status in {"stale", "estimated", "unpriced"}:
                    warnings.append(
                        f"{account.name}: {position.security.name} has {line_status} "
                        "value evidence."
                    )
            if not usd_cash_seen:
                balance_sheet_complete = False
                per_currency_incomplete[account.base_currency] = True
                warnings.append(
                    f"{account.name}: the selected position snapshot has no USD "
                    "cash line; account cash is unknown and no cash is assumed."
                )
                if not is_retirement and not is_liability_only:
                    cash_coverage_complete = False
            observation = latest_balances.get(account.id)
            if observation is not None:
                account_balance_ids[str(account.id)] = observation.id
                balance_revisions[str(account.id)] = observation.revision
                signed = (
                    -observation.amount
                    if observation.balance_kind == "liability"
                    else observation.amount
                )
                add_balance(
                    account=account,
                    effective_date=observation.as_of,
                    currency=observation.currency,
                    amount=signed,
                    bucket="excluded",
                    source=observation.source,
                    quality=observation.quality_status,
                    status="excluded_overlap",
                    detail=(
                        "Excluded because an owned-position snapshot covers this "
                        "account; the observation may overlap positions."
                    ),
                    position_snapshot_id=envelope.snapshot.id,
                    position_revision=envelope.snapshot.revision,
                    account_balance_id=observation.id,
                    balance_revision=observation.revision,
                )
                balance_sheet_complete = False
                warnings.append(
                    f"{account.name}: a separate balance observation was excluded "
                    "to avoid double counting against owned positions."
                )
            continue

        observation = latest_balances.get(account.id)
        if observation is None:
            add_balance(
                account=account,
                effective_date=None,
                currency=None,
                amount=None,
                bucket="unavailable",
                source=None,
                quality="unavailable",
                status="unavailable",
                detail="No eligible position snapshot or dated balance observation.",
            )
            balance_sheet_complete = False
            if not is_retirement and not is_liability_only:
                cash_coverage_complete = False
            warnings.append(
                f"{account.name}: no dated balance or position snapshot is available."
            )
            per_currency_incomplete[account.base_currency] = True
            continue

        amount = (
            -observation.amount
            if observation.balance_kind == "liability"
            else observation.amount
        )
        account_balance_ids[str(account.id)] = observation.id
        balance_revisions[str(account.id)] = observation.revision
        if observation.balance_kind == "liability":
            bucket = "liability"
        elif is_retirement:
            bucket = "restricted_asset"
        elif is_cash_account:
            bucket = "liquid_cash"
        elif observation.currency != "USD":
            bucket = "foreign_asset"
        else:
            bucket = "other_asset"
        included_in_cash = (
            is_cash_account
            and observation.balance_kind == "asset"
            and observation.currency == "USD"
        )
        status = observation.quality_status
        if observation.currency != "USD":
            warnings.append(
                f"{account.name}: {observation.currency} balance is shown in its "
                "own currency; no FX conversion is applied."
            )
        if status in {"stale", "estimated"}:
            warnings.append(f"{account.name}: latest balance is marked {status}.")
        add_balance(
            account=account,
            effective_date=observation.as_of,
            currency=observation.currency,
            amount=amount,
            bucket=bucket,
            source=observation.source,
            quality=observation.quality_status,
            status=status,
            detail=observation.balance_kind,
            included_in_starting_cash=included_in_cash,
            account_balance_id=observation.id,
            balance_revision=observation.revision,
        )
        if not included_in_cash and not is_retirement and not is_liability_only:
            cash_coverage_complete = False
            warnings.append(
                f"{account.name}: the balance observation does not identify USD "
                "liquid cash; available cash is unknown."
            )

    currency_rows: list[dict[str, Any]] = []
    for currency, bucket_values in sorted(totals.items()):
        net_worth = sum(bucket_values.values(), Decimal(0))
        currency_rows.append(
            {
                "currency": currency,
                **{key: _text(value) for key, value in bucket_values.items()},
                "known_net_worth": _text(net_worth),
                "completeness": (
                    "incomplete" if per_currency_incomplete[currency] else "complete"
                ),
            }
        )

    return {
        "balances": rows,
        "currency_balances": currency_rows,
        "liquid_cash_usd": liquid_cash_usd,
        "balance_sheet_complete": balance_sheet_complete,
        "cash_coverage_complete": cash_coverage_complete,
        "position_snapshot_ids": position_snapshot_ids,
        "position_revisions": position_revisions,
        "account_balance_ids": account_balance_ids,
        "balance_revisions": balance_revisions,
        "warnings": warnings,
        "currency_incomplete": dict(per_currency_incomplete),
    }


def _baseline(session: Session, accounts: list[Account], as_of: date) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 80
        return _baseline_calculate(session, accounts, as_of)


def _history(
    session: Session,
    account_ids: list[UUID],
    start: date,
    end: date,
    months: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    gaps: list[str] = []
    histories: dict[str, dict[str, Any]] = {}
    transaction_rows = list(
        session.execute(
            select(
                FinancialTransaction.id,
                FinancialTransaction.amount,
                FinancialTransaction.currency,
                FinancialTransaction.classification,
                FinancialTransaction.source_label,
            )
            .outerjoin(
                ActiveTransferTransaction,
                ActiveTransferTransaction.transaction_id == FinancialTransaction.id,
            )
            .where(
                FinancialTransaction.account_id.in_(account_ids),
                FinancialTransaction.status == "published",
                FinancialTransaction.posted_date >= start,
                FinancialTransaction.posted_date <= end,
                FinancialTransaction.classification.not_in(EXCLUDED_CLASSES),
                ActiveTransferTransaction.transaction_id.is_(None),
            )
            .order_by(FinancialTransaction.posted_date, FinancialTransaction.id)
            .limit(10001)
        )
    )
    if len(transaction_rows) > 10000:
        raise PlanningError("History exceeds 10,000 transactions; narrow the sample.")
    for row in transaction_rows:
        currency = row.currency or "UNKNOWN"
        aggregate = histories.setdefault(
            currency,
            {
                "currency": currency,
                "income": Decimal(0),
                "expenses": Decimal(0),
                "unclassified": Decimal(0),
                "published_count": 0,
                "classified_count": 0,
                "unclassified_count": 0,
                "income_count": 0,
                "expense_count": 0,
                "sources": set(),
            },
        )
        aggregate["published_count"] += 1
        aggregate["sources"].add(row.source_label)
        if row.amount is None or row.currency is None:
            gaps.append(
                f"Transaction {row.id} has no usable amount or currency and was "
                "excluded from historical cash-flow totals."
            )
            aggregate["unclassified_count"] += 1
            continue
        amount = Decimal(row.amount)
        if row.classification == "income":
            aggregate["income"] += amount
            aggregate["income_count"] += 1
            aggregate["classified_count"] += 1
        elif row.classification in SPENDING_CLASSES:
            aggregate["expenses"] -= amount
            aggregate["expense_count"] += 1
            aggregate["classified_count"] += 1
        elif row.classification == "unclassified":
            aggregate["unclassified"] += amount
            aggregate["unclassified_count"] += 1
        else:
            aggregate["classified_count"] += 1

    missing_date_count = int(
        session.scalar(
            select(func.count())
            .select_from(FinancialTransaction)
            .where(
                FinancialTransaction.account_id.in_(account_ids),
                FinancialTransaction.status == "published",
                FinancialTransaction.posted_date.is_(None),
            )
        )
        or 0
    )
    if missing_date_count:
        gaps.append(
            f"{missing_date_count} published transaction(s) have no posted date "
            "and cannot be placed in the selected history window."
        )

    transaction_history: list[dict[str, Any]] = []
    for currency, aggregate in sorted(histories.items()):
        income = aggregate["income"]
        expenses = aggregate["expenses"]
        transaction_history.append(
            {
                "currency": currency,
                "source_labels": sorted(aggregate["sources"]),
                "income_total": _text(income),
                "expenses_total": _text(expenses),
                "net_cash_flow": _text(income - expenses),
                "income_monthly_average": _text(
                    _round(income / months) if aggregate["income_count"] else None
                ),
                "expenses_monthly_average": _text(
                    _round(expenses / months) if aggregate["expense_count"] else None
                ),
                "published_transaction_count": aggregate["published_count"],
                "classified_transaction_count": aggregate["classified_count"],
                "unclassified_count": aggregate["unclassified_count"],
                "unclassified_signed_amount": _text(aggregate["unclassified"]),
            }
        )
    if not transaction_rows:
        gaps.append(
            "No eligible published transactions were found in this sample; no "
            "income or expense forecast was derived from history."
        )
    elif any(item["unclassified_count"] for item in transaction_history):
        gaps.append(
            "Published unclassified transactions remain visible but are excluded "
            "from historical income and expense totals."
        )
    gaps.append(
        "Transaction history includes only selected accounts' published rows; "
        "missing statements or feed coverage cannot be inferred from an empty month."
    )

    event_rows = list(
        session.execute(
            select(
                InvestmentEvent.cash_amount,
                InvestmentEvent.currency,
                InvestmentEvent.review_status,
                InvestmentEvent.quality_status,
                InvestmentEvent.source_label,
            )
            .where(
                InvestmentEvent.account_id.in_(account_ids),
                InvestmentEvent.event_type == "dividend",
                InvestmentEvent.effective_date >= start,
                InvestmentEvent.effective_date <= end,
            )
            .order_by(InvestmentEvent.effective_date, InvestmentEvent.id)
            .limit(10001)
        )
    )
    if len(event_rows) > 10000:
        raise PlanningError(
            "Dividend history exceeds 10,000 events; narrow the sample."
        )
    dividend_totals: dict[str, dict[str, Any]] = {}
    unreviewed_dividends = 0
    for event in event_rows:
        if (
            event.review_status != "reviewed"
            or event.quality_status not in {"reported", "manual"}
            or event.cash_amount is None
        ):
            unreviewed_dividends += 1
            continue
        aggregate = dividend_totals.setdefault(
            event.currency,
            {"total": Decimal(0), "count": 0, "sources": set()},
        )
        aggregate["total"] += Decimal(event.cash_amount)
        aggregate["count"] += 1
        aggregate["sources"].add(event.source_label)
    dividend_history = [
        {
            "currency": currency,
            "total": _text(aggregate["total"]),
            "monthly_average": _text(_round(aggregate["total"] / months)),
            "event_count": aggregate["count"],
            "source_labels": sorted(aggregate["sources"]),
        }
        for currency, aggregate in sorted(dividend_totals.items())
    ]
    if unreviewed_dividends:
        gaps.append(
            f"{unreviewed_dividends} dividend event(s) are unreviewed, incomplete, "
            "or missing cash amounts and are excluded from history."
        )
    if not dividend_history:
        gaps.append(
            "No reviewed dividend events were found in this sample; no dividend "
            "forecast was derived from history."
        )
    gaps.append(
        "Dividend events and classified transaction income are shown separately "
        "and may overlap; avoid counting the same observed payment twice."
    )
    return transaction_history, dividend_history, gaps


def _case(
    *,
    name: str,
    start: Decimal,
    request: PlanningScenarioRequest,
    projection_start: date,
    projection_complete: bool,
    income_factor: Decimal,
    expense_factor: Decimal,
    dividend_factor: Decimal,
) -> dict[str, Any]:
    income_base = Decimal(request.monthly_income)
    expense_base = Decimal(request.monthly_expenses)
    dividend_base = Decimal(request.monthly_dividends)
    recurring = sum(
        (Decimal(change.amount) for change in request.recurring_changes), Decimal(0)
    )
    one_time: dict[int, Decimal] = defaultdict(Decimal)
    for change in request.one_time_changes:
        one_time[change.month_offset] += Decimal(change.amount)

    cash = _round(start)
    months: list[dict[str, Any]] = []
    shortfall_month: int | None = 0 if cash <= 0 else None
    for index in range(1, request.horizon_months + 1):
        income = _round(income_base * income_factor)
        expenses = _round(expense_base * expense_factor)
        dividends = _round(dividend_base * dividend_factor)
        one_time_amount = _round(one_time.get(index, Decimal(0)))
        beginning = cash
        cash = _round(
            beginning + income - expenses + dividends + recurring + one_time_amount
        )
        if abs(cash) >= MAX_VALUE:
            raise PlanningError("Projected cash exceeds NUMERIC(28, 10) precision.")
        if shortfall_month is None and cash <= 0:
            shortfall_month = index
        months.append(
            {
                "month_index": index,
                "month_start": _next_month(projection_start, index - 1),
                "starting_cash": _text(beginning),
                "income": _text(income),
                "expenses": _text(expenses),
                "dividends": _text(dividends),
                "recurring_changes": _text(_round(recurring)),
                "one_time_changes": _text(one_time_amount),
                "ending_cash": _text(cash),
            }
        )
    return {
        "case": name,
        "starting_cash": _text(start),
        "ending_cash": _text(cash),
        "shortfall_month": shortfall_month,
        "runway_status": (
            "coverage_incomplete"
            if not projection_complete
            else "shortfall_within_horizon"
            if shortfall_month is not None
            else "beyond_horizon"
        ),
        "months": months,
    }


def simulate_planning_scenario(
    session: Session, request: PlanningScenarioRequest
) -> dict[str, Any]:
    if request.as_of > date.today():
        raise PlanningError("Planning as-of dates cannot be in the future.")
    requested_ids = set(request.account_ids)
    account_query = (
        select(Account)
        .where(Account.active.is_(True))
        .order_by(Account.name, Account.id)
    )
    if request.account_ids:
        account_query = account_query.where(Account.id.in_(request.account_ids))
    accounts = list(session.scalars(account_query.limit(101)))
    if not accounts:
        raise PlanningError("Select at least one active account.")
    if len(accounts) > 100:
        raise PlanningError("A planning scenario is limited to 100 accounts.")
    if requested_ids and {account.id for account in accounts} != requested_ids:
        raise PlanningError("Every selected account must be active.")

    first_of_month = date(request.as_of.year, request.as_of.month, 1)
    history_start = _next_month(first_of_month, -request.history_months)
    history_end = first_of_month - timedelta(days=1)
    projection_start = _next_month(first_of_month)
    baseline = _baseline(session, accounts, request.as_of)
    transaction_history, dividend_history, history_gaps = _history(
        session,
        [account.id for account in accounts],
        history_start,
        history_end,
        request.history_months,
    )
    warnings = list(baseline["warnings"])
    if request.starting_cash_override is None:
        starting_cash = baseline["liquid_cash_usd"]
        starting_cash_source = "observed_usd_cash"
        starting_cash_coverage = (
            "complete" if baseline["cash_coverage_complete"] else "incomplete"
        )
        projection_complete = baseline["cash_coverage_complete"]
        if not projection_complete:
            warnings.append(
                "Known USD cash is only a partial baseline because one or more "
                "selected accounts do not identify available liquid cash. Supply "
                "a starting cash override to model an explicit total."
            )
    else:
        starting_cash = Decimal(request.starting_cash_override)
        starting_cash_source = "user_override"
        starting_cash_coverage = "user_assumed"
        projection_complete = True
        warnings.append(
            "Starting cash is a user-entered total assumption and replaces observed "
            "USD cash for the projection."
        )
    if abs(starting_cash) >= MAX_VALUE:
        raise PlanningError("Starting cash exceeds NUMERIC(28, 10) precision.")

    percent = Decimal(request.sensitivity_percent) / Decimal(100)
    with localcontext() as context:
        context.prec = 60
        cases = [
            _case(
                name="conservative",
                start=starting_cash,
                request=request,
                projection_start=projection_start,
                projection_complete=projection_complete,
                income_factor=Decimal(1) - percent,
                expense_factor=Decimal(1) + percent,
                dividend_factor=Decimal(1) - percent,
            ),
            _case(
                name="base",
                start=starting_cash,
                request=request,
                projection_start=projection_start,
                projection_complete=projection_complete,
                income_factor=Decimal(1),
                expense_factor=Decimal(1),
                dividend_factor=Decimal(1),
            ),
            _case(
                name="optimistic",
                start=starting_cash,
                request=request,
                projection_start=projection_start,
                projection_complete=projection_complete,
                income_factor=Decimal(1) + percent,
                expense_factor=max(Decimal(0), Decimal(1) - percent),
                dividend_factor=Decimal(1) + percent,
            ),
        ]
    if any(
        Decimal(case["ending_cash"]) >= MAX_VALUE
        or Decimal(case["ending_cash"]) <= -MAX_VALUE
        for case in cases
    ):
        raise PlanningError("Projected cash exceeds NUMERIC(28, 10) precision.")
    if any(account.base_currency != "USD" for account in accounts):
        warnings.append(
            "The projection is USD-only. Account balances and observations remain "
            "grouped by their source currencies; no FX conversion is applied."
        )
    warnings.append(
        "Investment and retirement assets are shown separately and are never "
        "liquidated or treated as spendable cash."
    )
    warnings.append(
        "Historical transaction/dividend values are context only. Projection "
        "income, expenses, dividends, purchases, and changes use explicit user "
        "assumptions; they are not forecasts or guarantees."
    )
    warnings.append(
        "Liabilities are shown separately and are not automatically paid from cash. "
        "Enter a dated liability-payment change to model repayment."
    )
    for change in request.one_time_changes:
        if change.change_type == "purchase":
            warnings.append(
                f"Purchase assumption '{change.label}' is a cash outflow in month "
                f"{change.month_offset}; no investment sale, tax, or financing is "
                "modeled."
            )

    scenario_fingerprint = _digest(
        {
            "methodology_version": METHODOLOGY_VERSION,
            "request": request.model_dump(mode="json"),
            "balances": baseline["balances"],
            "transaction_history": transaction_history,
            "dividend_history": dividend_history,
            "cases": cases,
        }
    )
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "scenario_label": request.scenario_label,
        "as_of": request.as_of,
        "projection_start": projection_start,
        "horizon_months": request.horizon_months,
        "history_start": history_start,
        "history_end": history_end,
        "account_ids": [account.id for account in accounts],
        "account_names": [account.name for account in accounts],
        "account_position_revisions": baseline["position_revisions"],
        "position_snapshot_ids": baseline["position_snapshot_ids"],
        "account_balance_revisions": baseline["balance_revisions"],
        "account_balance_ids": baseline["account_balance_ids"],
        "balances": baseline["balances"],
        "currency_balances": baseline["currency_balances"],
        "balance_sheet_complete": baseline["balance_sheet_complete"],
        "liquid_cash_observed_usd": _text(baseline["liquid_cash_usd"]),
        "starting_cash_usd": _text(starting_cash),
        "starting_cash_source": starting_cash_source,
        "starting_cash_coverage": starting_cash_coverage,
        "transaction_history": transaction_history,
        "dividend_history": dividend_history,
        "history_gaps": history_gaps,
        "monthly_income_assumption": request.monthly_income,
        "monthly_income_source": request.monthly_income_source,
        "monthly_expense_assumption": request.monthly_expenses,
        "monthly_expenses_source": request.monthly_expenses_source,
        "monthly_dividend_assumption": request.monthly_dividends,
        "monthly_dividends_source": request.monthly_dividends_source,
        "sensitivity_percent": request.sensitivity_percent,
        "recurring_changes": request.recurring_changes,
        "one_time_changes": request.one_time_changes,
        "projection_status": "available" if projection_complete else "incomplete",
        "cases": cases,
        "warnings": list(dict.fromkeys(warnings)),
        "scenario_fingerprint": scenario_fingerprint,
        "canonical_records_mutated": False,
        "persisted": False,
    }
