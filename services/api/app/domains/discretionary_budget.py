"""Finance-owned monthly discretionary budgets."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MonthlyDiscretionaryBudget


class BudgetNotFound(LookupError):
    pass


class BudgetConflict(ValueError):
    pass


def replace_monthly_discretionary_budget(
    session: Session,
    *,
    period: str,
    expected_revision: int,
    amount: Decimal,
    currency: str,
    share_with_shopping: bool,
) -> MonthlyDiscretionaryBudget:
    row = session.scalar(
        select(MonthlyDiscretionaryBudget)
        .where(MonthlyDiscretionaryBudget.period == period)
        .with_for_update()
    )
    if row is None:
        if expected_revision != 0:
            raise BudgetConflict("budget_revision_conflict")
        row = MonthlyDiscretionaryBudget(
            id=uuid4(),
            period=period,
            amount=amount,
            currency=currency,
            share_with_shopping=share_with_shopping,
            revision=1,
        )
        session.add(row)
        session.flush()
        return row
    if row.revision != expected_revision:
        raise BudgetConflict("budget_revision_conflict")
    row.amount = amount
    row.currency = currency
    row.share_with_shopping = share_with_shopping
    row.revision += 1
    session.flush()
    return row


def read_monthly_discretionary_budget(
    session: Session, *, period: str
) -> MonthlyDiscretionaryBudget:
    row = session.scalar(
        select(MonthlyDiscretionaryBudget).where(
            MonthlyDiscretionaryBudget.period == period
        )
    )
    if row is None:
        raise BudgetNotFound("budget_not_found")
    return row
