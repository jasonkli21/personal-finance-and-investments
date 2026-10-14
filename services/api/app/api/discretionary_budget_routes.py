"""Authenticated Finance-owned monthly discretionary budget records."""

from __future__ import annotations

import re
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.discretionary_budget_contracts import (
    MonthlyDiscretionaryBudgetRead,
    MonthlyDiscretionaryBudgetWrite,
)
from app.db.transactions import run_database_unit
from app.domains.discretionary_budget import (
    BudgetConflict,
    BudgetNotFound,
    read_monthly_discretionary_budget,
    replace_monthly_discretionary_budget,
)

router = APIRouter(prefix="/v1/finance", tags=["Finance budgets"])


def _valid_period(period: str) -> bool:
    return (
        bool(re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", period)) and period[:4] != "0000"
    )


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


@router.put(
    "/discretionary-budgets/{period}",
    response_model=MonthlyDiscretionaryBudgetRead,
)
def put_monthly_discretionary_budget(
    period: str, request: Request, data: MonthlyDiscretionaryBudgetWrite
) -> MonthlyDiscretionaryBudgetRead:
    if not _valid_period(period):
        raise HTTPException(status_code=422, detail="budget_period_invalid")
    try:
        row = run_database_unit(
            _session_factory(request),
            lambda session: replace_monthly_discretionary_budget(
                session,
                period=period,
                expected_revision=data.expected_revision,
                amount=Decimal(data.amount),
                currency=data.currency,
                share_with_shopping=data.share_with_shopping,
            ),
        )
    except BudgetConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="budget_revision_conflict"
        ) from error
    return MonthlyDiscretionaryBudgetRead.model_validate(row)


@router.get(
    "/discretionary-budgets/{period}",
    response_model=MonthlyDiscretionaryBudgetRead,
    responses={404: {"description": "Budget not found"}},
)
def get_monthly_discretionary_budget(
    period: str, request: Request
) -> MonthlyDiscretionaryBudgetRead:
    if not _valid_period(period):
        raise HTTPException(status_code=422, detail="budget_period_invalid")
    try:
        with _session_factory(request)() as session:
            row = read_monthly_discretionary_budget(session, period=period)
    except BudgetNotFound as error:
        raise HTTPException(status_code=404, detail="budget_not_found") from error
    return MonthlyDiscretionaryBudgetRead.model_validate(row)
