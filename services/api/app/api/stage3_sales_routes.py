"""Read-only hypothetical lot-sale simulation API."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from app.api.stage3_contracts import SalesSimulationRead, SalesSimulationRequest
from app.domains import sales

router = APIRouter(prefix="/v1")


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


@router.post("/simulations/sales", response_model=SalesSimulationRead)
def simulate_lot_sales(
    data: SalesSimulationRequest, session: SessionDependency
) -> SalesSimulationRead:
    try:
        return SalesSimulationRead.model_validate(sales.simulate_sales(session, data))
    except sales.SalesSimulationError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.casefold() else 422
        raise HTTPException(status_code=status_code, detail=message) from exc
