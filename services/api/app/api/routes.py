"""Versioned HTTP routes for the manual portfolio workflow."""

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import (
    AccountCreate,
    AccountPatch,
    AccountRead,
    ErrorResponse,
    PositionReplace,
    PositionsEnvelope,
    PositionSnapshotRead,
    SecurityRead,
    SecurityResolution,
)
from app.db.models import Security
from app.db.transactions import run_database_unit
from app.domains import accounts, portfolio, securities

router = APIRouter(
    prefix="/v1",
    responses={
        404: {"model": ErrorResponse, "description": "Requested resource not found"},
        409: {"model": ErrorResponse, "description": "Revision or state conflict"},
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def _security_read(security: Security) -> SecurityRead:
    return SecurityRead(
        id=security.id,
        security_type=security.security_type,
        display_ticker=security.display_ticker,
        name=security.name,
        currency=security.currency,
    )


@router.get("/accounts", response_model=list[AccountRead])
def get_accounts(session: SessionDependency) -> list[AccountRead]:
    return [AccountRead.model_validate(row) for row in accounts.list_accounts(session)]


@router.post(
    "/accounts", response_model=AccountRead, status_code=status.HTTP_201_CREATED
)
def post_account(request: Request, data: AccountCreate) -> AccountRead:
    result = run_database_unit(
        request.app.state.session_factory,
        lambda session: accounts.create_account(session, data),
    )
    return AccountRead.model_validate(result)


@router.patch("/accounts/{account_id}", response_model=AccountRead)
def patch_account(
    request: Request, account_id: UUID, data: AccountPatch
) -> AccountRead:
    if any(value is None for value in data.model_dump(exclude_unset=True).values()):
        raise HTTPException(status_code=422, detail="Account fields cannot be null")
    try:
        result = run_database_unit(
            request.app.state.session_factory,
            lambda session: accounts.edit_account(session, account_id, data),
        )
    except accounts.AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    return AccountRead.model_validate(result)


@router.get("/securities/resolve", response_model=SecurityResolution)
def get_security_resolution(
    q: Annotated[str, Query(min_length=2, max_length=80)],
    session: SessionDependency,
) -> SecurityResolution:
    rows = securities.resolve_securities(session, q)
    limited = rows[:10]
    return SecurityResolution(
        status=(
            "unknown" if not rows else "resolved" if len(rows) == 1 else "ambiguous"
        ),
        matches=[_security_read(row) for row in limited],
    )


@router.get("/accounts/{account_id}/positions", response_model=PositionsEnvelope)
def get_positions(account_id: UUID, session: SessionDependency) -> PositionsEnvelope:
    try:
        return portfolio.read_positions(session, account_id)
    except accounts.AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc


@router.put("/accounts/{account_id}/positions", response_model=PositionSnapshotRead)
def put_positions(
    request: Request, account_id: UUID, data: PositionReplace
) -> PositionSnapshotRead:
    try:
        return run_database_unit(
            request.app.state.session_factory,
            lambda session: portfolio.replace_positions(session, account_id, data),
        )
    except accounts.AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except portfolio.StaleRevision as exc:
        raise HTTPException(
            status_code=409,
            detail="Positions changed since they were loaded; reload before saving.",
        ) from exc
    except portfolio.ArchivedAccount as exc:
        raise HTTPException(
            status_code=409, detail="Archived accounts cannot be edited."
        ) from exc
    except portfolio.UnknownSecurity as exc:
        raise HTTPException(
            status_code=422, detail="A selected security is not in the local catalog."
        ) from exc
    except portfolio.DuplicatePositionSecurity as exc:
        raise HTTPException(
            status_code=422, detail="A security can appear only once in a snapshot."
        ) from exc
    except portfolio.CurrencyMismatch as exc:
        raise HTTPException(
            status_code=422,
            detail="Position currency must match the selected security currency.",
        ) from exc
    except portfolio.CashPriceNotAllowed as exc:
        raise HTTPException(
            status_code=422,
            detail="Cash must be entered as a balance without a unit price.",
        ) from exc
    except portfolio.ValuationOutOfRange as exc:
        raise HTTPException(
            status_code=422,
            detail="The reported value exceeds the supported decimal precision.",
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A snapshot already exists for that effective date; reload first.",
        ) from exc
