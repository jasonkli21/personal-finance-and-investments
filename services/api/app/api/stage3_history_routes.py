"""Stage 3 historical event, reconciliation, and performance routes."""

from collections.abc import Iterator
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.stage3_contracts import (
    HistoryReconciliationRead,
    InvestmentEventCreate,
    InvestmentEventRead,
    PortfolioHistoryRead,
    PortfolioPerformanceRead,
)
from app.db.transactions import run_database_unit
from app.domains import history

router = APIRouter(prefix="/v1")


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def _raise_history(exc: history.HistoryError) -> HTTPException:
    status_code = 404 if "not found" in str(exc).casefold() else 422
    if "idempotency key was used" in str(exc).casefold():
        status_code = 409
    return HTTPException(status_code=status_code, detail=str(exc))


@router.post(
    "/portfolio/history/events",
    response_model=InvestmentEventRead,
    status_code=status.HTTP_201_CREATED,
)
def post_investment_event(
    request: Request, data: InvestmentEventCreate
) -> InvestmentEventRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: history.create_investment_event(session, data),
        )
    except history.HistoryError as exc:
        raise _raise_history(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="An event with this idempotency key was added concurrently.",
        ) from exc
    return InvestmentEventRead.model_validate(row)


@router.get("/portfolio/history", response_model=PortfolioHistoryRead)
def get_portfolio_history(
    session: SessionDependency,
    account_id: Annotated[UUID, Query()],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
) -> PortfolioHistoryRead:
    try:
        result = history.read_history(
            session,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    except history.HistoryError as exc:
        raise _raise_history(exc) from exc
    return PortfolioHistoryRead.model_validate(result)


@router.get("/portfolio/performance", response_model=PortfolioPerformanceRead)
def get_portfolio_performance(
    session: SessionDependency,
    account_id: Annotated[UUID, Query()],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
) -> PortfolioPerformanceRead:
    try:
        result = history.read_performance(
            session,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    except history.HistoryError as exc:
        raise _raise_history(exc) from exc
    return PortfolioPerformanceRead.model_validate(result)


@router.get("/portfolio/history/reconcile", response_model=HistoryReconciliationRead)
def get_history_reconciliation(
    session: SessionDependency,
    account_id: Annotated[UUID, Query()],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
) -> HistoryReconciliationRead:
    try:
        result = history.reconcile_history(
            session,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
    except history.HistoryError as exc:
        raise _raise_history(exc) from exc
    return HistoryReconciliationRead.model_validate(result)
