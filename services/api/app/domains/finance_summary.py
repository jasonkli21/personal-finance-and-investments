"""Deterministic cash-flow and dated net-worth summaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    AccountBalanceObservation,
    ActiveTransferTransaction,
    FinancialTransaction,
    SpendingCategory,
    TransactionSplit,
)
from app.domains import portfolio

SPENDING_CLASSES = ("expense", "refund", "fee")
EXCLUDED_CLASSES = ("transfer", "card_payment")


def create_balance_observation(
    session: Session,
    *,
    account_id: UUID,
    as_of: date,
    balance_kind: str,
    amount: Decimal,
    currency: str,
    source: str,
    quality_status: str,
    idempotency_key: str,
) -> AccountBalanceObservation:
    account = session.get(Account, account_id)
    if account is None or not account.active:
        raise ValueError("Active account not found.")
    if amount < 0:
        raise ValueError("Enter a nonnegative reported balance.")
    existing = session.scalar(
        select(AccountBalanceObservation).where(
            AccountBalanceObservation.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.account_id != account_id
            or existing.as_of != as_of
            or existing.balance_kind != balance_kind
            or existing.amount != amount
            or existing.currency != currency
            or existing.source != source
            or existing.quality_status != quality_status
        ):
            raise ValueError("Idempotency key was used for another balance.")
        return existing

    latest_revision = session.scalar(
        select(func.max(AccountBalanceObservation.revision)).where(
            AccountBalanceObservation.account_id == account_id,
            AccountBalanceObservation.as_of == as_of,
        )
    )
    row = AccountBalanceObservation(
        id=uuid4(),
        account_id=account_id,
        as_of=as_of,
        revision=int(latest_revision or 0) + 1,
        balance_kind=balance_kind,
        amount=amount,
        currency=currency,
        source=source,
        quality_status=quality_status,
        idempotency_key=idempotency_key,
    )
    session.add(row)
    session.flush()
    return row


def _next_month(month: date) -> date:
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)


def _month_totals(
    session: Session,
    *,
    month: date,
    account_id: UUID | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    month_start = date(month.year, month.month, 1)
    month_end = _next_month(month_start)
    included_cash_flow = and_(
        FinancialTransaction.classification.not_in(EXCLUDED_CLASSES),
        ActiveTransferTransaction.transaction_id.is_(None),
    )
    income = func.sum(
        case(
            (
                and_(
                    FinancialTransaction.classification == "income",
                    ActiveTransferTransaction.transaction_id.is_(None),
                ),
                FinancialTransaction.amount,
            ),
            else_=Decimal(0),
        )
    )
    unclassified_count = func.sum(
        case(
            (
                and_(
                    FinancialTransaction.classification == "unclassified",
                    ActiveTransferTransaction.transaction_id.is_(None),
                ),
                1,
            ),
            else_=0,
        )
    )
    unclassified_signed_amount = func.sum(
        case(
            (
                and_(
                    FinancialTransaction.classification == "unclassified",
                    ActiveTransferTransaction.transaction_id.is_(None),
                ),
                FinancialTransaction.amount,
            ),
            else_=Decimal(0),
        )
    )
    spending = -func.sum(
        case(
            (
                and_(
                    FinancialTransaction.classification.in_(SPENDING_CLASSES),
                    ActiveTransferTransaction.transaction_id.is_(None),
                ),
                FinancialTransaction.amount,
            ),
            else_=Decimal(0),
        )
    )
    cash_flow = func.sum(
        case((included_cash_flow, FinancialTransaction.amount), else_=Decimal(0))
    )
    included_count = func.sum(case((included_cash_flow, 1), else_=0))
    totals_query = (
        select(
            FinancialTransaction.currency,
            income.label("income"),
            spending.label("net_spending"),
            cash_flow.label("net_cash_flow"),
            included_count.label("transaction_count"),
            unclassified_count.label("unclassified_count"),
            unclassified_signed_amount.label("unclassified_signed_amount"),
        )
        .outerjoin(
            ActiveTransferTransaction,
            ActiveTransferTransaction.transaction_id == FinancialTransaction.id,
        )
        .where(
            FinancialTransaction.status == "published",
            FinancialTransaction.posted_date >= month_start,
            FinancialTransaction.posted_date < month_end,
        )
    )
    if account_id is not None:
        totals_query = totals_query.where(FinancialTransaction.account_id == account_id)
    totals_rows = session.execute(
        totals_query.group_by(FinancialTransaction.currency).order_by(
            FinancialTransaction.currency
        )
    )
    totals = [
        {
            "currency": row.currency,
            "income": str(row.income or 0),
            "net_spending": str(row.net_spending or 0),
            "net_cash_flow": str(row.net_cash_flow or 0),
            "transaction_count": int(row.transaction_count or 0),
            "unclassified_count": int(row.unclassified_count or 0),
            "unclassified_signed_amount": str(row.unclassified_signed_amount or 0),
        }
        for row in totals_rows
    ]

    split_amount = case(
        (TransactionSplit.id.is_not(None), TransactionSplit.amount),
        else_=FinancialTransaction.amount,
    )
    split_category_id = case(
        (TransactionSplit.id.is_not(None), TransactionSplit.category_id),
        else_=FinancialTransaction.category_id,
    )
    category_name = func.coalesce(SpendingCategory.display_name, "Uncategorized")
    categories_query = (
        select(
            FinancialTransaction.currency,
            split_category_id.label("category_id"),
            category_name.label("category_name"),
            (-func.sum(split_amount)).label("net_spending"),
        )
        .outerjoin(
            ActiveTransferTransaction,
            ActiveTransferTransaction.transaction_id == FinancialTransaction.id,
        )
        .outerjoin(
            TransactionSplit,
            TransactionSplit.transaction_id == FinancialTransaction.id,
        )
        .outerjoin(SpendingCategory, SpendingCategory.id == split_category_id)
        .where(
            FinancialTransaction.status == "published",
            FinancialTransaction.classification.in_(SPENDING_CLASSES),
            ActiveTransferTransaction.transaction_id.is_(None),
            FinancialTransaction.posted_date >= month_start,
            FinancialTransaction.posted_date < month_end,
        )
    )
    if account_id is not None:
        categories_query = categories_query.where(
            FinancialTransaction.account_id == account_id
        )
    category_rows = session.execute(
        categories_query.group_by(
            FinancialTransaction.currency, split_category_id, category_name
        ).order_by(FinancialTransaction.currency, category_name)
    )
    categories = [
        {
            "category_id": row.category_id,
            "category_name": row.category_name,
            "currency": row.currency,
            "net_spending": str(row.net_spending or 0),
        }
        for row in category_rows
    ]
    return totals, categories


def read_finance_summary(
    session: Session,
    *,
    month: date,
    as_of: date,
    account_id: UUID | None = None,
) -> dict[str, Any]:
    month_start = date(month.year, month.month, 1)
    totals, categories = _month_totals(
        session, month=month_start, account_id=account_id
    )
    transaction_gaps: list[str] = []
    if any(total["unclassified_count"] for total in totals):
        transaction_gaps.append(
            "Income and spending totals are incomplete because one or more "
            "transactions are unclassified."
        )
    accounts_query = select(Account).order_by(Account.name, Account.id)
    if account_id is not None:
        if session.get(Account, account_id) is None:
            raise ValueError("Account not found.")
        accounts_query = accounts_query.where(Account.id == account_id)
    accounts = list(session.scalars(accounts_query.limit(501)))
    if len(accounts) > 500:
        raise ValueError("Finance summary exceeds 500 accounts; select one account.")
    balances: list[dict[str, Any]] = []
    coverage_gaps: list[str] = []
    currency_incomplete: dict[str, bool] = defaultdict(bool)

    for account in accounts:
        positions = portfolio.read_positions(session, account.id, as_of)
        if positions.snapshot is not None:
            valuation = portfolio.read_owned_valuation(session, account.id, as_of)
            position_lines = cast(list[dict[str, Any]], valuation["lines"])
            snapshot_date = valuation["effective_date"]
            if not position_lines:
                balances.append(
                    {
                        "account_id": account.id,
                        "account_name": account.name,
                        "account_type": account.account_type,
                        "as_of": snapshot_date,
                        "currency": account.base_currency,
                        "amount": "0",
                        "source": positions.snapshot.source,
                        "quality_status": "reported",
                        "status": "valued",
                        "included": True,
                        "detail": "Empty accepted position snapshot",
                    }
                )
            for line in position_lines:
                value = line["value"]
                currency = line["value_currency"]
                quality = str(line["quality_status"])
                if value is None or currency is None:
                    status = "unpriced"
                    included = False
                    coverage_gaps.append(
                        f"{account.name}: {line['name']} has no usable value."
                    )
                elif quality == "stale":
                    status = "stale"
                    included = True
                    currency_incomplete[currency] = True
                    coverage_gaps.append(
                        f"{account.name}: {line['name']} uses a stale value."
                    )
                elif quality in {"estimated", "inferred", "unreviewed"}:
                    status = "foreign_currency" if currency != "USD" else "valued"
                    included = True
                    currency_incomplete[currency] = True
                    coverage_gaps.append(
                        f"{account.name}: {line['name']} uses {quality} data."
                    )
                elif currency != "USD":
                    status = "foreign_currency"
                    included = True
                else:
                    status = "valued"
                    included = True
                balances.append(
                    {
                        "account_id": account.id,
                        "account_name": account.name,
                        "account_type": account.account_type,
                        "as_of": snapshot_date,
                        "currency": currency,
                        "amount": str(value) if value is not None else None,
                        "source": line["price_source"] or "position snapshot",
                        "quality_status": quality,
                        "status": status,
                        "included": included,
                        "detail": line["ticker"] or line["name"],
                    }
                )
            latest_balance = session.scalar(
                select(AccountBalanceObservation)
                .where(
                    AccountBalanceObservation.account_id == account.id,
                    AccountBalanceObservation.as_of <= as_of,
                )
                .order_by(
                    AccountBalanceObservation.as_of.desc(),
                    AccountBalanceObservation.revision.desc(),
                )
                .limit(1)
            )
            if latest_balance is not None:
                balances.append(
                    {
                        "account_id": account.id,
                        "account_name": account.name,
                        "account_type": account.account_type,
                        "as_of": latest_balance.as_of,
                        "currency": latest_balance.currency,
                        "amount": str(
                            -latest_balance.amount
                            if latest_balance.balance_kind == "liability"
                            else latest_balance.amount
                        ),
                        "source": latest_balance.source,
                        "quality_status": latest_balance.quality_status,
                        "status": "valued",
                        "included": False,
                        "detail": (
                            "Skipped because an owned-position snapshot covers "
                            "this account."
                        ),
                    }
                )
            continue

        latest_balance = session.scalar(
            select(AccountBalanceObservation)
            .where(
                AccountBalanceObservation.account_id == account.id,
                AccountBalanceObservation.as_of <= as_of,
            )
            .order_by(
                AccountBalanceObservation.as_of.desc(),
                AccountBalanceObservation.revision.desc(),
            )
            .limit(1)
        )
        if latest_balance is None:
            coverage_gaps.append(f"{account.name}: no balance or position snapshot.")
            balances.append(
                {
                    "account_id": account.id,
                    "account_name": account.name,
                    "account_type": account.account_type,
                    "as_of": None,
                    "currency": None,
                    "amount": None,
                    "source": None,
                    "quality_status": "unavailable",
                    "status": "unavailable",
                    "included": False,
                    "detail": "Add a dated account balance or positions snapshot.",
                }
            )
            for total in totals:
                currency_incomplete[total["currency"]] = True
            continue

        signed_amount = (
            -latest_balance.amount
            if latest_balance.balance_kind == "liability"
            else latest_balance.amount
        )
        quality = latest_balance.quality_status
        if quality == "stale":
            status = "stale"
            currency_incomplete[latest_balance.currency] = True
            coverage_gaps.append(f"{account.name}: latest balance is marked stale.")
        elif latest_balance.currency != "USD":
            status = "foreign_currency"
            if quality == "estimated":
                currency_incomplete[latest_balance.currency] = True
                coverage_gaps.append(f"{account.name}: latest balance is estimated.")
        else:
            status = "valued"
            if quality == "estimated":
                currency_incomplete[latest_balance.currency] = True
                coverage_gaps.append(f"{account.name}: latest balance is estimated.")
        balances.append(
            {
                "account_id": account.id,
                "account_name": account.name,
                "account_type": account.account_type,
                "as_of": latest_balance.as_of,
                "currency": latest_balance.currency,
                "amount": str(signed_amount),
                "source": latest_balance.source,
                "quality_status": quality,
                "status": status,
                "included": True,
                "detail": latest_balance.balance_kind,
            }
        )

    net_worth_values: dict[str, Decimal] = defaultdict(Decimal)
    with localcontext() as context:
        context.prec = 80
        for line in balances:
            if line["included"] and line["amount"] is not None and line["currency"]:
                net_worth_values[line["currency"]] += Decimal(line["amount"])
    net_worth = [
        {
            "currency": currency,
            "known_amount": str(amount),
            "completeness": (
                "incomplete"
                if currency_incomplete[currency] or coverage_gaps
                else "complete"
            ),
        }
        for currency, amount in sorted(net_worth_values.items())
    ]
    return {
        "month": month_start,
        "as_of": as_of,
        "transaction_policy": (
            "Posted date; income uses signed credits; spending is the negative of "
            "signed expense, refund and fee amounts; confirmed transfers and "
            "card-payment classifications are excluded."
        ),
        "currency_totals": totals,
        "category_totals": categories,
        "net_worth": net_worth,
        "balances": balances,
        "coverage_gaps": transaction_gaps + coverage_gaps,
        "exclusions": [
            "No currency conversion is applied; net worth is grouped by currency.",
            (
                "A balance observation is excluded when an owned-position "
                "snapshot is available for the account."
            ),
            "ETF look-through exposure is excluded from net worth.",
        ],
    }
