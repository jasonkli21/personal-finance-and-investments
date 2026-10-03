"""Finance summaries and source-labelled dated balances."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import (
    AccountBalanceCreate,
    AccountBalanceRead,
    ErrorResponse,
    FinanceSummaryRead,
)
from app.db.models import AccountBalanceObservation
from app.db.transactions import run_database_unit
from app.domains.finance_summary import (
    create_balance_observation,
    read_finance_summary,
)

router = APIRouter(
    prefix="/v1",
    responses={
        404: {"model": ErrorResponse, "description": "Requested record not found"},
        409: {"model": ErrorResponse, "description": "Revision or identity conflict"},
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def _balance_read(row: AccountBalanceObservation) -> AccountBalanceRead:
    return AccountBalanceRead.model_validate(
        {
            "id": row.id,
            "account_id": row.account_id,
            "as_of": row.as_of,
            "revision": row.revision,
            "balance_kind": row.balance_kind,
            "amount": str(row.amount),
            "currency": row.currency,
            "source": row.source,
            "quality_status": row.quality_status,
        }
    )


@router.post(
    "/finance/balances",
    response_model=AccountBalanceRead,
    status_code=status.HTTP_201_CREATED,
)
def post_balance_observation(
    request: Request, data: AccountBalanceCreate
) -> AccountBalanceRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: create_balance_observation(
                session,
                account_id=data.account_id,
                as_of=data.as_of,
                balance_kind=data.balance_kind,
                amount=Decimal(data.amount),
                currency=data.currency,
                source=data.source,
                quality_status=data.quality_status,
                idempotency_key=data.idempotency_key,
            ),
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).casefold() else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A balance observation was added concurrently; reload and retry.",
        ) from exc
    return _balance_read(row)


@router.get("/finance/summary", response_model=FinanceSummaryRead)
def get_finance_summary(
    session: SessionDependency,
    month: Annotated[date, Query(description="Any date in the month to summarize")],
    as_of: Annotated[date | None, Query()] = None,
    account_id: Annotated[UUID | None, Query()] = None,
) -> FinanceSummaryRead:
    try:
        result = read_finance_summary(
            session,
            month=month,
            as_of=as_of or date.today(),
            account_id=account_id,
        )
    except ValueError as exc:
        code = 404 if "not found" in str(exc).casefold() else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return FinanceSummaryRead.model_validate(result)
